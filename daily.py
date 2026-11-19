"""The daily routine, meant to run automatically every morning (Windows Task Scheduler):

  1. Download last night's box scores        (retries up to 3 times if the NBA site fails)
  2. Verify nothing is missing               (every finished game on the schedule must be in the data)
  3. Grade yesterday's predictions and PrizePicks entries (score.py)
  4. Retrain the model once a week           (only if the data is complete; a model with no new
                                              games to learn from is kept as it is)

Writes a full log to logs/daily_YYYY-MM-DD.log and a summary to data/status.json.
Run it by hand any time:  python daily.py   (or  python daily.py --retrain)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from nbaline.paths import EXPERIMENTS, LOGS, MODELS, POINTS_META, ROOT, STATUS

RETRAIN_EVERY_DAYS = 7


def model_age() -> int:
    """Days since the points model was last trained."""
    return (date.today() - date.fromisoformat(json.loads(POINTS_META.read_text())["trained_on"])).days


def step(name: str, script: list[str], log) -> bool:
    log.write(f"\n===== {name}  ({datetime.now():%H:%M:%S}) =====\n")
    log.flush()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    exe = Path(sys.executable).with_name("python.exe")  # also works when started windowless (pythonw)
    r = subprocess.run([str(exe), *script], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log.write(f"----- {name}: {'OK' if r.returncode == 0 else f'FAILED (exit {r.returncode})'}\n")
    log.flush()
    return r.returncode == 0


def main():
    if sys.stdout is None:  # started by Task Scheduler with pythonw (no console)
        sys.stdout = open(os.devnull, "w")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrain", action="store_true", help="retrain today even if the model is recent")
    args = ap.parse_args()
    os.chdir(ROOT)
    LOGS.mkdir(exist_ok=True)
    logfile = LOGS / f"daily_{date.today()}.log"
    status = dict(run_at=datetime.now().isoformat(timespec="seconds"), log=str(logfile.name))

    with open(logfile, "a", encoding="utf-8") as log:
        # 1. fetch (the NBA stats site sometimes times out, so try a few times)
        ok = False
        for attempt in range(3):
            ok = step(f"fetch_data (attempt {attempt + 1})", ["fetch_data.py"], log)
            if ok:
                break
            time.sleep(120)
        status["fetch_ok"] = ok

        # 2. verify against the official schedule
        from nbaline import features as F
        from nbaline import schedule as S
        p, t = F.load_raw()
        status["data_through"] = str(p["GAME_DATE"].max().date())
        try:
            missing = S.missing_finals(set(t["GAME_ID"]), refresh=True)
            status["missing_games"] = [f"{r.GAME_DATE} {r.AWAY}@{r.HOME}" for r in missing.itertuples()]
        except Exception as e:  # schedule unreachable: can't verify
            status["missing_games"] = None
            log.write(f"\nCould not check the schedule: {e}\n")
        complete = status["missing_games"] == []

        # 3. grade predictions
        status["score_ok"] = step("score", ["score.py"], log)

        # 4. weekly retrain, only on complete data
        status["model_age_days"] = model_age()
        train_ok, status["retrained"] = True, False
        if (args.retrain or status["model_age_days"] >= RETRAIN_EVERY_DAYS) and complete:
            started = time.time()
            train_ok = step("train", ["train.py"], log)
            if train_ok and (EXPERIMENTS / "stat_models.csv").exists():  # rebounds, assists, PRA, ...
                train_ok = step("train_stats", ["stat_models.py", "--train"], log)
            # models with nothing new to learn are kept as they are: were any actually retrained?
            status["retrained"] = any(f.stat().st_mtime >= started for f in MODELS.glob("*.pkl"))
            status["model_age_days"] = model_age()

    status["ok"] = bool(ok and complete and status["score_ok"] and train_ok)
    STATUS.write_text(json.dumps(status, indent=2))

    print(f"NBALine daily update  {status['run_at']}")
    print(f"  data through     : {status['data_through']}  ({'complete' if complete else 'INCOMPLETE'})")
    if status["missing_games"]:
        print(f"  missing games    : {', '.join(status['missing_games'][:6])}"
              f"{' ...' if len(status['missing_games']) > 6 else ''}")
    elif status["missing_games"] is None:
        print("  missing games    : couldn't check (schedule unreachable)")
    print(f"  predictions graded: {'yes' if status['score_ok'] else 'FAILED'}")
    print(f"  model            : {status['model_age_days']} days old{' (retrained today)' if status['retrained'] else ''}")
    print(f"  full log         : logs/{logfile.name}")
    sys.exit(0 if status["ok"] else 1)


if __name__ == "__main__":
    main()
