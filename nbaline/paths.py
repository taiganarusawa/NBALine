"""Every file and folder the project reads or writes, defined once."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"                      # downloaded data + local databases (not in git)
RAW = DATA / "raw"                        # one CSV per season, straight from stats.nba.com
PLAYER_LOGS = DATA / "player_logs.csv"    # every player box score, all seasons
TEAM_LOGS = DATA / "team_logs.csv"        # every team box score, all seasons
DUNKS = DATA / "dunks.csv"                # made dunks per player per game (box scores don't count them)
STARTERS = DATA / "starters.csv"          # who started each game, from NBA.com's daily lineups (2023-24 on)
TRACKING = DATA / "tracking.csv"          # passes, potential assists, rebound chances, drives, touches per game
SHOTS = DATA / "shots.csv"                # where and how each player shot (zones, shot types) per game
HUSTLE = DATA / "hustle.csv"              # deflections, box outs, contested shots, loose balls per game
FEATURES_CACHE = DATA / "features.pkl.gz"   # model inputs for every past game, compressed (rebuilt when stale)
INJURY_REPORTS = DATA / "injury_reports"  # cached official injury report PDFs, parsed
PICKEM_DB = DATA / "prizepicks.db"        # your checked lines, pasted boards and entries
STATUS = DATA / "status.json"             # result of the last daily update

MODELS = ROOT / "models"                  # trained models (not in git)
POINTS_MODEL = MODELS / "pipeline.pkl"
POINTS_META = MODELS / "meta.json"
STATS_META = MODELS / "stats.json"        # which stat models exist and how they tested

EXPERIMENTS = ROOT / "experiments"        # experiment results and tuned settings
LOGS = ROOT / "logs"                      # one log file per daily update
PREDICTIONS_LOG = ROOT / "predictions_log.csv"   # every prediction made with predict.py
PAGE = ROOT / "frontend" / "dist"         # the web page, built from frontend/ (npm run build)


def stat_model(key: str) -> Path:
    """Saved model for a non-points stat, e.g. stat_model("REB") -> models/stat_REB.pkl."""
    return MODELS / f"stat_{key}.pkl"
