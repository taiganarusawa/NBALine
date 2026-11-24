# NBALine

NBALine predicts whether an NBA player will go **More or Less** than a PrizePicks line. It gives a
calibrated chance for each side and explains the reasons behind it.

- Paste a PrizePicks board and get the best picks for the entry you plan to play.
- Follow your entries live during the games, and see why each pick hit or missed afterwards.
- Runs on your own computer, and you can open it from your phone.
- Uses free, public NBA data only.

**Guides:** [GUIDE.md](GUIDE.md) shows how to use the app. [TRAINING.md](TRAINING.md) shows how the
models were built and tested.

> Not betting advice.

---

## Contents

- [What it does](#what-it-does)
- [How the predictions work](#how-the-predictions-work)
- [Where the data comes from](#where-the-data-comes-from)
- [Getting started](#getting-started)
- [Project layout](#project-layout)
- [Commands](#commands)
- [How well it works](#how-well-it-works)

---

## What it does

The web app has five tabs:

| Tab | What you do there |
|---|---|
| **Best lines** | Paste the PrizePicks board and get the top 10 picks for your entry type, plus lineups to play: a 6- or 5-pick Flex of standard lines, a safer Goblin Power or a high-risk Demon Power |
| **Check lines** | Look up any player, stat and line |
| **My entries** | Build a slip, save what you played, and follow it live during the games |
| **Results** | Your record and profit, and how the model did against PrizePicks |
| **Long shots** | Lines that hit even though the model gave them little chance |

The **⟳ Update data & model** button downloads last night's games, grades your entries and retrains
the models, all in one click.

The same predictions also work from the command line:

```
Stephen Curry (GSW) vs. NOP  |  2026-11-09  |  line 28.5
----------------------------------------------------------------------
Projection     : 26.7 pts   (typical range 17-37, median 25.7)
OVER   36.5%   book 51.9% at -108   edge -15.4%
UNDER  63.5%   book 52.8% at -112   edge +10.6%
Verdict        : LEAN UNDER
OUT (NOP)      : Zion Williamson (12 FGA/g), Trey Murphy III (11 FGA/g), Yves Missi (5 FGA/g)
Biggest factors (pts vs. an average rotation player):
   +6.2  Recent-weighted scoring average = 29.4
   +4.7  Long-run weighted scoring average = 27.4
   ...
```

This is a real example: Warriors vs. Pelicans on Nov 9, 2026, using that day's line and injury report.

---

## How the predictions work

```
 stats.nba.com ──► fetch_data.py ──► data/player_logs.csv, team_logs.csv, shots.csv, starters.csv, tracking.csv, hustle.csv
                                            │
                    nbaline/features.py ◄───┘   inputs for each game, built only from games before it
                            │
       experiments.py ──► nbaline/recipes.py ──► train.py / stat_models.py ──► models/*.pkl
       (lab notebook)     (winning settings)      (train the final models)
                                                                 │
 schedule + injury report + lineups ──► nbaline/predictor.py ◄────┘   player + stat + line -> P(over)
                                                │
                       ┌────────────────────────┴────────────────────────┐
                 predict.py (command line)                  webapp.py + frontend/ (PrizePicks app)
                                                            nbaline/pickem/: read boards, rank,
                                                            payouts, save + grade entries
```

### The models

- **Points** has its own model:
  - XGBoost (70%) blended with a neural net (30%).
  - It also learns how much each player's scoring swings from game to game.
  - 57 inputs, trained on ten seasons (about 181,000 player-games).
- **25 other stats** each get their own XGBoost model:
  - The main stats and combos: rebounds, assists, PRA, P+R, P+A, R+A, fantasy score.
  - Threes and shooting: 3-PT made and attempted, FG made and attempted, free throws made and
    attempted, two-pointers made and attempted.
  - Rebound splits: offensive and defensive rebounds.
  - Defense and other counts: steals, blocks, blocks+steals, turnovers, personal fouls, dunks.
  - Yes-or-no stats: double-doubles and triple-doubles. These predict a chance directly.

### What the models look at

Every input for a game is built only from games played before it.

- His recent and season averages, his per-minute rates and his shooting efficiency.
- His minutes, rest days, back-to-backs, and how far he is into coming back from an absence.
- Both teams' pace and ratings, and how likely a blowout is.
- Who's out on both teams, from the official injury report, and for 17 stats his likely share of the
  shots, assists and rebounds they leave (the top shooter left takes the most).
- Tonight's starting lineup, once it's posted.
- NBA.com player tracking (rebound chances, touches, drives) for the 6 stats where it tested better,
  measured against the league each night because NBA.com has changed how it counts them.
- His shot profile (shots at the rim, midrange, corner 3s, pull-ups) for the 10 stats where it tested
  better, mostly shot and free-throw attempts.
- Hustle stats (deflections, contested shots, box outs) for the 6 stats where they tested better, mostly
  steals and blocks.
- Tonight's defense vs. where he shoots (does it give up his kind of shots?), for 3-PT attempts and makes
  and FG attempts.

### Labels on a line

- **Less tested:** a stat added recently that hasn't been tested yet. It stays out of Best lines while
  **Only well-tested stats** is checked, until `python stat_models.py --evaluate --train --only <KEY>`
  tests it (1–2 minutes per stat).
- **Low minutes:** players averaging under 15 minutes in their last 10 games. The models were built on
  players above that, and they're noticeably less accurate below it.

---

## Where the data comes from

| Information | Source | Notes |
|---|---|---|
| Box scores | stats.nba.com, through `nba_api` | Official stats. Games still in progress are skipped |
| Schedule, tip-off times | Official NBA schedule | A typed opponent that doesn't match it is refused |
| Who's out | Official NBA injury report (PDF) | Out and Doubtful count as out; Questionable is flagged |
| Who's starting | NBA.com's daily starting lineups (2023-24 on) | "Expected" during the day, "Confirmed" about 30 min before tip-off |
| Player tracking | NBA.com's camera-tracking stats (2017-18 on) | Potential assists, rebound chances, drives, touches. Counted differently from 2024-25, so measured against the league |
| Dunks and shot profile | NBA.com's shot charts (2017-18 on) | Every shot's zone and type; box scores don't count dunks |
| Hustle stats | NBA.com's hustle stats (2017-18 on) | Deflections, contested shots, box outs. Logged by people at each game, so measured against the league |
| Live games | NBA.com's live box scores; ESPN's when NBA.com doesn't answer | Refreshed every 15 seconds while a game is on |
| PrizePicks lines | **You paste them** | NBALine never scrapes PrizePicks |

How far to trust each source is covered in [GUIDE.md](GUIDE.md#data-sources-in-detail).

---

## Getting started

### Install (once)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python fetch_data.py      # download ten seasons of box scores
python train.py           # train the points model
python stat_models.py --train
cd frontend && npm install && npm run build    # build the web page (needs Node.js 22+)
```

**Optional, an NVIDIA graphics card:**
- Training runs on the GPU when it can, about 3× faster per model.
- It needs NVIDIA driver 580 or newer. Set `NBALINE_DEVICE=cpu` to train on the CPU instead.
- Predictions always run on the CPU, so the app never needs the GPU.

### Run it

**Double-click `NBALine.bat`.** Your browser opens at http://127.0.0.1:5055.

- Keep the black window open while you use the app, and close it to stop.
- The app only listens on your own computer.
- To open it from your phone, see [GUIDE.md](GUIDE.md#on-your-phone).

---

## Project layout

```
nbaline/                 the library: everything the commands and the web app share
  paths.py               where every file lives
  features.py            box scores -> model inputs (rolling averages, minutes, absences, opponent, ...)
  modeling.py            the model pipeline: XGBoost / neural net / blend, early stopping, uncertainty
  recipes.py             the settings that won the experiments (used to train the real models)
  evaluate.py            scoring: CRPS, Brier, calibration, interval coverage
  schedule.py            official NBA schedule (opponent, home/away, tip-off)
  injuries.py            official NBA injury report PDFs, downloaded and parsed
  lineups.py             NBA.com's daily starting lineups
  tracking.py            NBA.com player tracking per game: potential assists, rebound chances, drives, touches
  shots.py               NBA.com shot charts per game: dunks, shots by zone, self-created jumpers
  hustle.py              NBA.com hustle stats per game: deflections, contested shots, box outs, loose balls
  predictor.py           the prediction engine: {player, stat, line} -> calibrated over/under chance
  updater.py             the web app's one-click "Update data & model" job
  pickem/                PrizePicks
    payouts.py           payout tables, entry odds, break-even per pick
    board.py             reads a pasted PrizePicks board
    ranking.py           ranks a board's lines; Goblin/Demon lines kept separate
    lines.py             cached line analysis for the web app
    calibration.py       the chance adjustment, learned from the model's record against PrizePicks
    live.py, ingame.py   games in progress: live box scores, and the model's chance from here
    espn.py              ESPN's live box scores, the backup when NBA.com's feed doesn't answer
    jerseys.py           players' jersey numbers
    explain.py           why a graded pick hit or missed, in plain words
    store.py             SQLite: checked lines, pasted boards, entries; grading and results
frontend/                the web page: React + TypeScript, built with Vite
  src/pages/             one component per tab
  src/components/        shared pieces: header, live box score, entry card, badges, tooltips
  src/context/           what the tabs share: game date, players, the entry slip
fetch_data.py  train.py  stat_models.py  predict.py  score.py  daily.py  webapp.py     commands
experiments.py  tune.py  learning_curve.py                                             model research
```

---

## Commands

| Command | What it does |
|---|---|
| `python webapp.py` | Starts the web app (or double-click `NBALine.bat`) |
| `python fetch_data.py` | Downloads the latest box scores, shot charts, lineups, tracking and hustle stats |
| `python train.py` | Trains the points model |
| `python stat_models.py --train` | Trains the other 25 stat models (`--evaluate` tests them) |
| `python predict.py "Player" 28.5` | One prediction on the command line, with its reasons |
| `python score.py` | Grades your logged predictions and the app's entries |
| `python daily.py [--retrain]` | The morning routine: download, check nothing's missing, grade, retrain weekly |
| `python experiments.py NAME ...` | Runs model experiments; `--compare A B` tests whether B really beats A |
| `python tune.py`, `python learning_curve.py` | Hyperparameter search; error by training round |
| `python -m nbaline.schedule` | Today's games |
| `python -m nbaline.injuries --team GSW` | The official injury report for a team |
| `python -m nbaline.lineups` | Downloads the starting lineups of every game day not saved yet |

Daily command-line use and the automatic morning update are in [GUIDE.md](GUIDE.md#command-line).

---

## How well it works

**On seasons the models never saw:**
- **Points:** on the 2025-26 season the projection missed by **4.79 points** on average, against 5.00
  for a smart average of his recent games. So far this season it's 4.72. The chances are well
  calibrated.
- **The 25 other stats:** every one beats a no-model baseline on 2025-26. The gains are small, from
  0.0002 to 0.0145 in Brier score.

**Against real PrizePicks lines** (13,970 graded standard lines over 14 nights, Nov 10–23, 2026):

| | Model's More picks right | Model's Less picks right |
|---|---|---|
| Non-scoring stats (rebounds, assists, threes, ...) | 55.8% of 3,048 | 55.4% of 5,297 |
| Scoring stats (points, PRA, P+R, P+A, fantasy) | 50.1% of 1,396 | 51.9% of 4,229 |

- A 5- or 6-pick Flex needs 54.2% per pick to break even.
- **The picks the app shows** (54.2%+ for one side after the chance adjustment) were right **57.4%** of
  the time, over 5,770 lines:
  - Non-scoring stats: 59.4%. Scoring stats: 54.2%, right at break-even.
  - Today's adjustment was learned from these same nights, so expect a little less on new ones.
- On scoring stats the model has almost no edge across all lines. PrizePicks prices those lines
  carefully.
- **By stat**, among the shown picks with 100+ lines:
  - Best: Blocked Shots 81% (122 lines), Blks+Stls 67%, Turnovers 65%, Steals 64%.
  - Weakest: Free Throws Made 51%, FG Made 52%, Pts+Asts and Fantasy Score 53%.
  - The Results tab has every stat.

**The surer the model, the more often it's right, but its own chances were too sure:**

| Model's chance for its side | Right | Lines |
|---|---|---|
| 50–54% | 51.8% | 4,880 |
| 54–60% | 51.7% | 4,994 |
| 60–65% | 54.9% | 2,355 |
| 65–70% | 58.8% | 1,012 |
| 70%+ | 72.6% | 729 |

That's why the app shrinks its chances toward 50% before showing them
([the chance adjustment](GUIDE.md#the-chance-adjustment)). It now keeps about 55% of each lean, so a 70%
lean shows as 61%.

**Goblins and Demons** (More only), where the model's chances match what happened:
- Goblins: the model said 59.8% on average, and 61.2% went over (5,250 lines).
- Demons: it said 24.6%, and 25.4% went over (3,924 lines). The Demons it gave 60% or more went over
  79% of the time, but that's only 48 lines.

These are two weeks of lines, so the numbers will still move. Each night's lines are graded the next
morning.

An older test against made-up lines (a player's recent average) showed about 62% right. That number is
inflated, as [TRAINING.md §1](TRAINING.md) explains: real lines are set more sharply than averages.
