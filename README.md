# NBALine

Predicts whether an NBA player goes **over or under** a line (points, rebounds, assists, threes, PRA and every other full-game PrizePicks stat), with a calibrated probability, an edge against the sportsbook's odds, and the reasons behind it.

Real example: Warriors vs. Pelicans on Nov 9, 2026, with the line and absences from that day's previews and injury report.

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

**The points model** blends Poisson XGBoost (70%) with a neural net (30%) and adds a volatility model for the uncertainty. It has 46 inputs and is trained on ten seasons (180k player-games).

**25 more stats** each have their own model: rebounds, assists, 3-PT made and attempted, steals, blocks, turnovers, PRA, P+R, P+A, R+A, blocks+steals, fantasy score, FG made and attempted, free throws made and attempted, offensive and defensive rebounds, two-pointers made and attempted, personal fouls, dunks, double-doubles and triple-doubles. All 25 beat a no-model baseline on a season they never saw, and all are well calibrated. Double- and triple-doubles happen or they don't, so their models predict a chance directly. Dunks aren't in box scores, so they're counted from each season's shot chart.

A stat added later starts out untested: it shows a "less tested" label and stays out of Best lines while **Only well-tested stats** is checked, until `python stat_models.py --evaluate --train --only <KEY>` tests it (about 1–2 minutes per stat).

**Bench players** (under 15 minutes a game over their last 10) get a "low minutes" label and are treated the same way: the models were built and tested on players above that, and are noticeably less accurate below it.

How everything was built and tested is in **[TRAINING.md](TRAINING.md)**.

## How it works

```
 stats.nba.com ──► fetch_data.py ──► data/player_logs.csv, team_logs.csv, dunks.csv, starters.csv, tracking.csv
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

**Project layout**

```
nbaline/                 the library: everything the commands and the web app share
  paths.py               where every file lives
  features.py            box scores -> model inputs (rolling averages, minutes, absences, opponent, ...)
  modeling.py            the model pipeline: XGBoost / neural net / blend, early stopping, uncertainty
  recipes.py             the settings that won the experiments (used to train the real models)
  evaluate.py            scoring: CRPS, Brier, calibration, interval coverage
  schedule.py            official NBA schedule (opponent, home/away, tip-off)
  injuries.py            official NBA injury report PDFs, downloaded and parsed
  lineups.py             NBA.com's daily starting lineups: who started each game, and who's starting tonight
  tracking.py            NBA.com player tracking per game: potential assists, rebound chances, drives, touches
  predictor.py           the prediction engine: {player, stat, line} -> calibrated over/under chance
  updater.py             the web app's one-click "Update data & model" job
  pickem/                PrizePicks
    payouts.py           payout tables, entry odds, break-even per pick
    board.py             reads a pasted PrizePicks board (whole page or typed lines)
    ranking.py           ranks a board's lines; Goblin/Demon lines kept separate
    lines.py             cached line analysis for the web app (model + history + final result)
    calibration.py       pulls the model's chances toward 50% by its record against PrizePicks (self-tested)
    live.py, ingame.py   games in progress: live box scores, and the model's chance from here
    jerseys.py           players' jersey numbers, for My entries
    explain.py           why a graded pick hit or missed, in plain words, from the box scores
    store.py             SQLite: checked lines, pasted boards, entries; grading and results
frontend/                the web page: React + TypeScript, built with Vite (npm run build -> frontend/dist)
  src/pages/             one component per tab: BestLines, CheckLines, MyEntries, Results, LongShots
  src/components/        shared pieces: header, live box score, entry card, line details, badges, tooltips
  src/context/           what the tabs share: startup info, game date, players, the entry slip
  src/types.ts, api.ts   the server's JSON as TypeScript types, and the calls to it
fetch_data.py  train.py  stat_models.py  predict.py  score.py  daily.py  webapp.py     commands
experiments.py  tune.py  learning_curve.py                                             model research
```

## Where the information comes from (and how far to trust it)

| Information | Source | Automatic? | How reliable |
|---|---|---|---|
| Box scores of finished games | stats.nba.com via `nba_api` | Yes | **High.** Official NBA stats. Games still in progress are skipped (live halftime box scores once leaked in, and that's fixed). Every team box score must add up to its players': a download made as games finish can catch one side before the other, so a team row that's behind is rebuilt from its players, and a game whose player rows are behind waits for the next download. Grades from the last 3 days are checked again whenever new box scores arrive, so a late stat correction fixes them too. `nba_api` is an unofficial wrapper, so the NBA can change or rate-limit it. |
| Which team a player is on | His most recent game | Yes | Lags after a trade until his first game with the new team |
| Opponent, home/away, tip-off time | Official NBA schedule (`nbaline/schedule.py`) | Yes | **High.** Filled in automatically; if you type an opponent or home/away that doesn't match the schedule, the prediction is refused. Predictions made after tip-off are flagged. |
| Who's out | Official NBA injury report PDF (`nbaline/injuries.py`), the latest one before tip-off | Yes | **High** for what's been filed: Out/Doubtful players are treated as out, Questionable ones are flagged. Teams update it every 15 minutes, so predict close to tip-off. Late scratches after the last report aren't caught. If no report covers the game (too far ahead, or offline), absences are **guessed** from recent games, and the output says so. |
| Who's starting | NBA.com's daily starting lineups (`nbaline/lineups.py`, the file behind its "Today's Starting Lineups" page), from 2023-24 on | Yes | **Good.** Starters are "Expected" through the day (team news and reporters) and "Confirmed" about 30 minutes before tip-off; expected ones can still change. Each line shows tonight's role ("Starting · confirmed", "lineup not posted yet"), and a **Starting tonight** / **Bench tonight** tag when it's not his usual role. The same file has each team's inactive list, so a player on it shows **Inactive tonight** (it catches late scratches the injury report misses). Past games' starters are saved to `data/starters.csv` for training. The models use tonight's role once it's posted (a real gain in testing, `TRAINING.md` 4e) and leave it blank until then, which tested the same as before. It's an unofficial file, so NBA.com could change it; without it the models go by how often each player has started lately. |
| Player tracking: potential assists, rebound chances, drives, touches | NBA.com's camera-tracking dashboards, one game day at a time (`nbaline/tracking.py`), from 2017-18 on | Yes | **Good.** Checked against the box scores: the same players, and every assist count matched. NBA.com has none for 16 of 1,469 game days (the 2020 restart). Used only by the 6 stats where it tested better: Turnovers, Rebounds, Offensive Rebounds, Rebs+Asts, Two Pointers Made and Free Throws Attempted (`TRAINING.md` 4f). An unofficial source like the box scores; if a day's download fails, the inputs use his other recent games. |
| Lines and odds | **You type them** from your sportsbook | No | Lines move during the day; enter the number you can actually bet |

## Setup (once)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python fetch_data.py
python train.py
cd frontend && npm install && npm run build    # the web page (needs Node.js 22+)
```

**Faster training with an NVIDIA graphics card (optional):** XGBoost builds its trees on the GPU whenever it can, about 3× faster per model here (`TRAINING.md` section 7). It needs an NVIDIA driver new enough for XGBoost's CUDA 13 build (version 580 or newer). Without one, or with `NBALINE_DEVICE=cpu`, training uses the CPU. Predictions always run on the CPU, so the web app doesn't need the GPU.

## The PrizePicks web app

**Double-click `NBALine.bat`** (or a desktop shortcut to it; `NBALine.ico` is the basketball icon for one). Your browser opens at http://127.0.0.1:5055. Keep the black window open while you use it, and close it to stop. The app only runs on your computer.

**On your phone** (or any of your devices, from anywhere), privately, with [Tailscale](https://tailscale.com) (free): install it on the PC and the phone and sign in with the same account, then run once on the PC:

```bash
tailscale serve --bg 5055
```

It prints a private address like `https://<pc-name>.<tailnet>.ts.net` that only your Tailscale devices can open; NBALine itself still only listens on this computer. In Safari, Share → **Add to Home Screen** gives NBALine the basketball icon and opens it full screen, like an app. The PC has to be on with NBALine running. `tailscale serve --https=443 off` stops it.

When NBALine's code changes while it's running, the page says so. New page files need only **Refresh now**. New Python code needs the server to start again: **Restart now** stops it, `NBALine.bat` starts it again in the same window, and the page reloads by itself a few seconds later. It won't restart during an update, so a retrain is never cut off. (Started some other way, like `python webapp.py`, NBALine can't restart itself: stop it and start it again.)

Each tab has its own address, so you can bookmark one and the browser's back button moves between them: `/bestlines`, `/check`, `/entries`, `/results` and `/longshots`.

**Changing the page.** The page is a React + TypeScript app in `frontend/`. NBALine serves the built copy in `frontend/dist`, so once it's built (Setup), using the app needs nothing but Python. After editing anything in `frontend/src`, rebuild it (needs [Node.js](https://nodejs.org) 22+):

```bash
cd frontend
npm install        # once
npm run build      # type-checks, then writes frontend/dist; an open page offers to refresh
```

While working on the page, `npm run dev` serves it at http://localhost:5173 with instant reloads, passing `/api` calls to a running NBALine.

1. **Best lines:**
   - **Get the board in.** On the PrizePicks website press **Ctrl+A, Ctrl+C** and paste the whole page into the box, or type lines one per line (`Stephen Curry 28.5 Points`).
   - **Rank it.** Pick the entry you plan to play and press **Find the best lines**. Every line goes through its stat's model, and you get the **top 10 picks** (More or Less), each with the model's chance and how far it clears that entry's break-even.
   - **What it handles for you:**
     - Each card's team, opponent and game day are read from the page, and the date is set from the day shown on the cards.
     - Players listed Out on the official injury report are left out, and Questionable ones are flagged.
     - A card whose team doesn't match our data (a recent trade) is set aside.
   - **More-only cards** (Goblin/Demon lines) are listed separately with the model's More chance, not ranked, because they pay differently. Which kind each one is comes from PrizePicks' own tag in the copied page. The **All / Demons / Goblins** buttons show one kind at a time.
   - **Set aside rather than guessed:** first-half, quarter and other part-game lines, stats PrizePicks has that we don't model, and unknown or ambiguous names. Each one is shown with the reason.
   - **Games in progress:** lines whose game has started are followed live (every 15 seconds while the tab is open): his stat so far, the clock, his pace and a bar toward the line, plus the model's **live chance**, its pre-game projection updated with his stats so far, his minutes and the time left, and a live pick when one side reaches 54.2% (`nbaline/pickem/ingame.py`). Check lines shows the same for started games, and a line's live box says "feed not answering" when NBA.com's live feed doesn't. Tested on Nov 10's games at the end of Q1, halftime and the end of Q3, it beat both the pre-game chance and "he keeps his pace"; one night so far.
2. **Check lines:** type each player, pick the stat, and type the PrizePicks line, then press **Analyze**. You get the model's chance of More vs. Less, the expected average and median, injury news, the reasons behind it, and how often the player went over this line in his last 10 games.
   - **Looking back:** pick an earlier game date to see what the model would have said before tip-off.
     - It uses only games before that date, plus that day's official injury report.
     - Once the game is final, the card shows the actual number and whether the model's pick was right (✓ or ✗).
     - These after-the-fact checks don't count toward the model's record on the Results tab, because you're choosing the lines after knowing how they turned out.
3. **My entries:** press **+ Add** on Best lines or **+ More / + Less** on Check lines to put a pick on your slip (it turns green; click again to take it off), or add one by hand. Choose Power or Flex, type the amount, and check the payout numbers match your PrizePicks app. With a **Profit boost** promo, type its % (e.g. 30): PrizePicks adds it to the winnings above your entry fee, so with 30% a 7x payout pays 8.8x and 1.25x pays 1.325x. A payout of 1x or less gets it on the whole amount, so 0.4x pays 0.52x. Type the payouts as PrizePicks shows them before the boost; each box shows what it comes to with it, and the entry is graded with it, reverted payouts included. The app shows the model's chance of cashing and its expected return. Press **Save entry** for what you actually played. Tick **Protected play** for a PrizePicks protected play: if it loses outright, it stays in your record but is left out of profit and ROI (anything it pays back counts as usual). An entry saved without the box ticked can be marked from its card. **Payouts** on an open entry's card changes its payouts and boost after you've saved it, for example to the reverted payouts PrizePicks shows once a pick is removed (the row that pays now is marked); its chances and payout follow at once (`/api/entries/<id>/payouts`). Open entries show each player's jersey number (from NBA.com's player index, `nbaline/pickem/jerseys.py`), each pick's chance when saved and now, and **when each game starts** until it tips off. **During the games** they follow the NBA's live box scores, refreshing every 15 seconds while the tab is open and at once when you come back to it. If NBA.com's live feed stops answering, the picks keep the last numbers it sent, a note says so, and NBALine keeps trying (the server window says why it stopped and when it's back). Each pick shows its stat so far, minutes and game clock, and how far it is from the line ("needs 2", "room for 1"). A progress bar fills toward the line: white in play, green won, red lost, grey push or void. A **Pace %** pill shows where he finishes at his current rate, as a share of the line (4 of 5 at the buzzer = 80%). It's green when on pace for your side, amber when behind. The **List / Grid** switch next to "Open entries" shows one entry per row or two side by side (remembered in your browser). A red dot marks picks whose game is on, and players on the floor right now are tagged and highlighted. It shows **✓ hit** or **✗ lost** the moment it's decided (More can't lose once he passes the line; Less can't win). Each entry shows what's locked in and the most it can still pay (`nbaline/pickem/live.py`, `/api/entries/live`). A **Chances now** dropdown under each open entry (closed, it still shows the chance of a profit and the average payout; open or closed is remembered) gives what the slip showed before you saved it, kept up to date: the chance of a profit, of any payout, the average payout, and every amount it can still pay with its chance ("5 of 6 · $2.29 · 22.7%"). Each pick counts with its chance now: the latest re-check before its game, the live chance during it (`ingame.py`), and as it ended once decided. So after a miss, "6 of 6" is crossed out and the rest show what's still in reach (`payouts.outcome_chances`). A pick on a whole-number line can also finish exactly on it: a push, so it reverts and the lineup is paid on one pick fewer. Each pick's push chance comes from the model before its game and from the live chance during it (a live pick sitting on its line shows "push 54%"), and the amounts only a push leads to are listed with "+1 push" ("4 of 4 · +1 push · $7.50"). It assumes picks are independent and that players still to come play.
4. **Results:** after the games, press **Update results** (or let the morning `daily.py` do it). Every entry is graded the PrizePicks way: a player who doesn't play, or finishes exactly on the line, "reverts", and the lineup is paid from its reverted payouts by how many picks are left (for a 6-pick Flex: 5 left pays 10x/2x/0.4x, 4 left 6x/1.5x, 3 left 3x/1x, 2 left 3x, 1 left 1.5x; all reverted is a refund). The slip shows that table under **If players revert**, editable like the payouts, since Goblins and Demons change it. PrizePicks' payouts change, so if it paid a different amount than shown, press **Edit** on that graded entry and type in what it paid. Your record and profit then use that amount (won, partial or lost follow it), re-grading keeps it, and the card shows what the app had worked out, with a button to go back to it (`/api/entries/<id>/paid`). You get profit and ROI, your pick hit rate, and **Model vs. PrizePicks**, a Brier score where 0.250 is a coin flip and lower means the model's probabilities beat the lines.
   - **Why it won / lost** under each graded entry opens to each pick, misses first, with what was different about his night:
     - how unusual the night was ("his most rebounds in 20 games");
     - his minutes against his usual, and what changed them (foul trouble, a blowout, overtime, a close game);
     - a fast or slow game;
     - for a combined stat, the part that rose most and the part that fell most;
     - hot or cold shooting, more or fewer shots, and his share of the team's shots;
     - where the line sat, when his last 10 games were clearly on one side of it ("The line was low for him: 23.6 average in his last 10 games, over 15.5 in 9 of them", so an ordinary 20-point night still cleared it);
     - when nothing else pushed it the way it went, how his night compared with his usual ("A big night: 5 offensive rebounds (usually 2.2)"), so every hit or miss says why.

     Each of these pushed his number up or down, so they're sorted by the way the pick went. **Why it hit / Why it missed** lists what pushed his number the way it went. **Worked against it** (a hit) or **Helped, but not enough** (a miss) lists what pushed it the other way: 32 minutes instead of his usual 22 on a Less that still hit was luck, not the reason it hit. Last comes how close it finished, what the model expected, and where the line sat in his last 10 games.

     Above the picks it notes picks that won or lost together: several on one player, or players in the same game. The entry's odds treat picks as independent, and these aren't. It's all worked out from the player box scores with fixed rules (`nbaline/pickem/explain.py`), so it only says what the numbers show: an injury during the game shows up as "only 14 min", without a reason.
   - **Model's pick by stat** and **by how sure it was** show how often the side the model favoured was right on standard lines, each with the range the true rate is probably in and colored against break-even (54.2%). A model worth following is right more often the surer it is; "Model was" says how far its chance ran above or below that. Click a column of the by-stat table to sort it. A stat gets a **trusted** badge once it has 10+ graded nights and even the low end of its range is above break-even.
   - **Chance adjustment** corrects a model that's too sure of itself against PrizePicks. It learns one number from every graded standard line, how much of the model's lean to keep (with 0.4, a 70% lean shows as 58%), and applies it to every standard line's chance on the page. Goblins, Demons and yes/no props are left alone. It switches itself on only after 10 graded nights, and only if, scoring each night with what it had learned from the nights before, it beat the model's own chances. The tile says whether it's on and how it tested; hovering a chance shows the model's own number. Saved checks always keep the model's own chance, so it never learns from itself (`nbaline/pickem/calibration.py`).
5. **Long shots:** pick a day and see the lines that hit although the model gave them little chance: every line you pasted or checked, on the side that won (Goblins and Demons only when they went over). Filter to Demons, Goblins or standard lines, and sort by the model's chance, lowest or highest first; lines you played are marked (`/api/long-shots`).

**⟳ Update data & model** (top right) does the whole refresh in one click:
- downloads the latest box scores
- checks nothing is missing against the official schedule
- grades your entries
- retrains the points model and the 25 other stat models

It takes about 7 minutes on a day with new games, and under a minute when there's nothing new (a model with no new data to learn from is kept as it is). It runs in the background, so you can keep using the app; a banner shows each step. It's the same job as `python daily.py --retrain`.

Things to know:
- **Break-even per pick:** 2-pick Power 57.7%, 3-pick Power 58.5%, 5/6-pick Flex 54.2%. A "Lean" means the model is at least 54.2% on one side.
- **Average vs. median.** A pick can say LESS even when the average is above the line, for example "average 26.1, median 25.2" on a 25.5 line. A few big nights pull the average up, but the median is the player's typical game, and the median decides More vs. Less. This is why the model often leans Less on lines set near a player's average.
- **Default payouts are typical values, not guaranteed.** PrizePicks changes them, and they differ by state, so edit them on the slip to match your app. Goblins and Demons change every payout by an amount PrizePicks doesn't publish: it depends on the line, and two of your one-Goblin 6-pick Flexes paid 19.2x and 16.6x for 6 of 6. So copy those from the app, the reverted payouts too, since a Goblin still in the lineup after a pick is removed still lowers them. How PrizePicks pays is summed up at the top of `nbaline/pickem/payouts.py`.
- **The expected return assumes picks are independent.** Picks from the same game often move together.
- **Everything you paste is saved** in `data/prizepicks.db`:
  - every line the model analyzes, with its prediction
  - the pasted board text itself (an identical re-paste is skipped)
  - your entries

  After the games, every saved line is graded. For scoring, each player and stat counts once a day, at the last line you saw before tip-off, because PrizePicks moves lines during the day. Goblins and Demons are scored separately, each kind on its own: how often its lines went over against the model's chance, overall and grouped by the model's chance.
- **Your results grade the model; they don't train it (yet).** It trains on every NBA game, which already includes yours. After a few weeks of saved boards, the PrizePicks line itself can be tested as a model input.

## Daily use (command line)

```bash
python fetch_data.py                                       # 1. latest games (~30 s)
python -m nbaline.schedule                                 # 2. tonight's games and tip-off times
python -m nbaline.injuries --team GSW                      #    (optional) the official injury report
python predict.py "Stephen Curry" 28.5                     # 3a. one line (opponent comes from the schedule)
python predict.py --slate slate.csv                        # 3b. or a whole slate
python fetch_data.py && python score.py                    # 4. after games: grade everything
```

- Who's out comes from the official injury report automatically. If you predict a player who's listed Out or Doubtful, it refuses and shows why. `--out "Name"` adds anyone the report doesn't have yet (a late scratch you saw on X/Twitter, for example).
- `--date 2026-11-11` predicts a future game. If the player's team doesn't play that day, it tells you when they play next.
- Slate CSV columns: `player,line,over_odds,under_odds,out` (several outs separated by `;`). The players and lines in `slate_example.csv` are placeholders; put in real lines from your sportsbook.
- `--no-schedule --opp BOS --home` lets you try a matchup that isn't on the schedule (marked as unchecked in the log).
- `--over-odds -120 --under-odds +100` uses the real prices (default -110 each way).
- Every prediction is saved to `predictions_log.csv`. `score.py` grades the log: projection error, calibration, record and profit for leans, and **model vs. sportsbook Brier score**. That last one shows whether the model actually knows something the book doesn't. Judge it after ~300 lines, not 30.
- Retrain weekly with `python train.py` (points, about 2 minutes) and `python stat_models.py --train` (the other stats, 4 at a time, about 5 minutes) so recent games shape the models. `daily.py --retrain` does both. A model with no new data is kept as it is, and each retrain reuses the early stopping and calibration of the last one (they only use past seasons), so it gives exactly the models a full retrain would, in about half the time ([TRAINING.md](TRAINING.md#7-retraining-faster-with-the-same-models)).

## Keeping it up to date automatically

`daily.py` runs the whole morning routine in one go:

1. Downloads last night's box scores (retries up to 3 times if the NBA site fails).
2. **Verifies** every finished game on the official schedule is in the data.
3. Grades yesterday's predictions and PrizePicks entries (`score.py`).
4. Retrains the points model and the 25 other stat models once a week, but only if the data is complete. A model with no new games to learn from is kept as it is.

It writes a full log to `logs/daily_YYYY-MM-DD.log` and a summary to `data/status.json`.

Windows Task Scheduler runs it every morning at 9:00. If the computer was off, it runs as soon as it's back on. To set that up (once, in PowerShell):

```powershell
$a = New-ScheduledTaskAction -Execute "$PWD\.venv\Scripts\pythonw.exe" -Argument "daily.py" -WorkingDirectory "$PWD"
$t = New-ScheduledTaskTrigger -Daily -At 9am
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "NBALine daily update" -Action $a -Trigger $t -Settings $s
```

To remove it later: `Unregister-ScheduledTask -TaskName "NBALine daily update"`.

**Safety net:** even if the morning run never happens, `predict.py` checks the data against the schedule every time. It prints a big **DATA IS OUT OF DATE** warning if any finished game is missing, and warns if the model is over 10 days old.

## Commands

| Command | What it does |
|---|---|
| `python fetch_data.py` | Downloads every player and team box score from stats.nba.com (`nba_api`) |
| `python train.py` | Trains and saves the points model (the recipe in `nbaline/recipes.py`) |
| `python stat_models.py --evaluate / --train [--only XDD,XDUNK]` | Tests (walk-forward, ~1 min per stat) / trains the other 25 stat models |
| `python predict.py "Player" 28.5` | One prediction on the command line, with explanation; logged to `predictions_log.csv` |
| `python score.py` | Grades everything: logged predictions and the web app's entries and checked lines |
| `python daily.py [--retrain]` | Morning routine: fetch, verify against the schedule, grade, weekly retrain |
| `python webapp.py` | The PrizePicks web app (or double-click `NBALine.bat`) |
| `python experiments.py NAME ...` | Run walk-forward experiments; `--compare A B` tests whether B really beats A |
| `python tune.py`, `python learning_curve.py` | Hyperparameter search; error by boosting round / epoch |
| `python -m nbaline.schedule`, `python -m nbaline.injuries --team GSW` | Today's games; the official injury report |
| `python -m nbaline.lineups` | Downloads the starting lineups of every game day not saved yet (`fetch_data.py` does this too) |

## Honest status

- On seasons it never saw, the model misses by **4.83 points** on average (vs. 5.03 for a smart average), and its probabilities are well calibrated.
- **The 12 tested stat models** each beat a no-model baseline on the 2025-26 season. The gains are modest (about 0.005–0.012 Brier), and real PrizePicks lines are sharper than the test lines, so expect a smaller edge in practice.
- It has **not yet been tested against real sportsbook lines**. The ~62% hit rate against synthetic lines is inflated (see TRAINING.md §1). Logging real lines with `predict.py` and grading them with `score.py` is the real test.

Not betting advice.
