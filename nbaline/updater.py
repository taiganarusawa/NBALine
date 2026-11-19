"""The web app's one-click "Update data & model".

It runs `daily.py --retrain` in the background (download box scores -> check nothing is missing ->
grade -> retrain every model) and reports progress. daily.py stamps the start time of each step in
its log; the progress bar compares those with how long each step took last time.
"""
import json
import re
import subprocess
import sys
import time
from datetime import date, datetime
from typing import Callable

from .paths import DATA, EXPERIMENTS, LOGS, ROOT, STATUS

STEPS = ["fetch_data", "score", "train", "train_stats"]
STEP_NAMES = {"fetch_data": "Downloading the latest box scores",
              "score": "Grading predictions and PrizePicks entries",
              "train": "Retraining the points model",
              "train_stats": "Retraining the rebounds, assists, PRA and other stat models"}
# typical seconds per step; replaced by the real timings of your last completed update
DEFAULT_TIMING = {"fetch_data": 25, "score": 8, "train": 140, "train_stats": 280}
TIMING_FILE = DATA / "update_timing.json"
_STEP_LINE = re.compile(r"===== (\w+).*\((\d\d:\d\d:\d\d)\) =====")   # e.g. "===== train  (09:01:02) ====="


def last_run() -> dict | None:
    """Summary of the last daily update (data/status.json), or None."""
    return json.loads(STATUS.read_text()) if STATUS.exists() else None


class UpdateJob:
    """One background update at a time. `on_finish` runs once when it completes (e.g. clear caches)."""

    def __init__(self, on_finish: Callable[[], None] | None = None):
        self.on_finish = on_finish
        self.proc = None
        self.output = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        """Start an update. Returns False if one is already running."""
        if self.running:
            return False
        self.log = LOGS / f"daily_{date.today()}.log"
        self.log_start = self.log.stat().st_size if self.log.exists() else 0   # this run's part of the log
        self.started, self.finished, self.output = time.time(), None, None
        self.proc = subprocess.Popen([sys.executable, "daily.py", "--retrain"], cwd=ROOT,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace",
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True

    def status(self) -> dict:
        """What the progress banner shows."""
        resp = dict(running=False, last=last_run())
        if self.proc is None:
            return resp
        running = self.running
        starts = self._step_starts()
        if not running and self.output is None:  # just finished: collect the summary, learn the timings
            self.output = self.proc.stdout.read() if self.proc.stdout else ""
            self.finished = time.time()
            self._save_timing(starts, self.finished)
            if self.on_finish:
                self.on_finish()
        now = self.finished or time.time()
        steps = self._active_steps()
        pct, left, current = self._progress(starts, now)
        resp.update(running=running, step=STEP_NAMES.get(current, "Starting"),
                    step_no=steps.index(current) + 1 if current in steps else 0, steps=len(steps),
                    percent=100.0 if not running else pct, seconds_left=0 if not running else left,
                    elapsed=int(now - self.started), exit_code=self.proc.returncode, output=self.output,
                    last=last_run())
        return resp

    # ------------------------------------------------------------ progress estimate
    @staticmethod
    def _active_steps() -> list[str]:
        """The steps an update runs (the other-stat models only once they've been set up)."""
        if (EXPERIMENTS / "stat_models.csv").exists():
            return STEPS
        return [s for s in STEPS if s != "train_stats"]

    @staticmethod
    def _timing() -> dict:
        try:
            return {**DEFAULT_TIMING, **json.loads(TIMING_FILE.read_text())}
        except (OSError, ValueError):
            return dict(DEFAULT_TIMING)

    def _step_starts(self) -> dict:
        """When each step of this run started, read from the timestamps daily.py writes in its log."""
        starts = {}
        if not self.log.exists():
            return starts
        day = datetime.fromtimestamp(self.started).date()
        with open(self.log, encoding="utf-8", errors="replace") as f:
            f.seek(self.log_start)
            for line in f:
                m = _STEP_LINE.match(line)
                if m and m.group(1) in STEPS and m.group(1) not in starts:
                    t = datetime.combine(day, datetime.strptime(m.group(2), "%H:%M:%S").time()).timestamp()
                    starts[m.group(1)] = t + (86400 if t < self.started - 3600 else 0)  # ran past midnight
        return starts

    def _progress(self, starts: dict, now: float) -> tuple[float, float, str | None]:
        """(percent done, seconds left, current step), from how long each step usually takes."""
        steps, timing = self._active_steps(), self._timing()
        total = sum(timing[s] for s in steps)
        current = max(starts, key=starts.get) if starts else None
        if current not in steps:
            return 1.0, total, None
        i = steps.index(current)
        done = sum(timing[s] for s in steps[:i])
        in_step = now - starts[current]
        frac = min(in_step / timing[current], 0.97)  # never claim a step is done before it is
        pct = 100 * (done + frac * timing[current]) / total
        left = max(timing[current] - in_step, 3) + sum(timing[s] for s in steps[i + 1:])
        return round(pct, 1), round(left), current

    def _save_timing(self, starts: dict, finished: float):
        """Remember how long each step really took, so the next progress bar is accurate."""
        steps = self._active_steps()
        order = [s for s in steps if s in starts]
        if len(order) < len(steps):
            return  # a step was skipped (e.g. no retrain): don't learn from a partial run
        if not (last_run() or {}).get("retrained"):
            return  # the models were already up to date: those quick training steps would mislead the next estimate
        timing = self._timing()
        for s, nxt in zip(order, order[1:] + [None]):
            took = (starts[nxt] if nxt else finished) - starts[s]
            timing[s] = round(0.5 * timing[s] + 0.5 * max(took, 1), 1)  # blend with past runs
        TIMING_FILE.write_text(json.dumps(timing, indent=2))
