# Using NBALine

A walkthrough of the web app, tab by tab, plus the command line and the automatic morning update.
For what NBALine is and how it's built, start with the [README](README.md).

## Contents

- [Starting the app](#starting-the-app)
- [Best lines](#best-lines)
- [Check lines](#check-lines)
- [My entries](#my-entries)
- [Results](#results)
- [Long shots](#long-shots)
- [Update data & model](#update-data--model)
- [Things to know](#things-to-know)
- [Data sources in detail](#data-sources-in-detail)
- [Command line](#command-line)
- [Changing the web page](#changing-the-web-page)

---

## Starting the app

**Double-click `NBALine.bat`** (or a desktop shortcut to it; `NBALine.ico` is its basketball icon).

- Your browser opens at http://127.0.0.1:5055.
- Keep the black window open while you use it. Close it to stop.
- Each tab has its own address, so you can bookmark one: `/bestlines`, `/check`, `/entries`,
  `/results` and `/longshots`.

### On your phone

Use [Tailscale](https://tailscale.com) (free) to open NBALine privately from your phone, from anywhere.

1. Install Tailscale on the PC and the phone, and sign in with the same account on both.
2. On the PC, run once:
   ```bash
   tailscale serve --bg 5055
   ```
3. It prints a private address like `https://<pc-name>.<tailnet>.ts.net`. Only your own Tailscale
   devices can open it.
4. In Safari, **Share → Add to Home Screen** gives NBALine an app icon and opens it full screen.

The PC has to be on with NBALine running. To stop sharing: `tailscale serve --https=443 off`.

### When NBALine's code changes

The page tells you when there's something new:

- **New page files:** press **Refresh now**.
- **New Python code:** press **Restart now**. The server restarts in the same window and the page
  reloads by itself a few seconds later.
- It won't restart during an update, so a retrain is never cut off.
- Started some other way (like `python webapp.py`)? Then stop it and start it again yourself.

---

## Best lines

### Get the board in

- On the PrizePicks website press **Ctrl+A, Ctrl+C**, then paste the whole page into the box.
- Or type lines one per line: `Stephen Curry 28.5 Points`.

### Rank it

Pick the entry you plan to play and press **Find the best lines**.

- Every line goes through its stat's model.
- You get the **top 10 picks** (More or Less).
- Each pick shows the model's chance and how far it clears that entry's break-even.

### Best lineup

On top of the list, NBALine builds the entry to play. The **Standard / Safer / High risk** buttons
switch between three options, and the one you pick stays chosen.

**Standard: a 6-pick Flex of standard lines.**

- Every pick clears the 6-pick Flex break-even (54.2%), best chance first.
- One pick per player, since all of a player's lines rise and fall with his minutes.
- At most 2 picks from one game. On a small slate it allows more, rather than leave the lineup short.
- Only well-tested stats, and no player who is inactive or questionable tonight.
- No stat whose lines like these have clearly lost (below).
- With only 5 such lines it's a 5-pick Flex (54.3%). With fewer there's no lineup that night, and the
  card lists the few that clear.

**Each stat's record.** Under every pick: how that stat's graded lines did when the page showed them
at 54.2% or more, at the chance it would have shown that night. Hover for its likely range.

- **Red**: clearly losing, even the high end of its range is under 54.2%. The stat is left out of the
  lineup, and its lines in the list below get a **⚠ Losing record** badge.
- **Green**: clearly winning, even the low end is above 54.2%.
- **Grey**: too close or too few to tell. In November 2026 every stat was here: Points, for one, was
  right 60.6% of 71 lines, but its range ran from 49% to 72%.

It shows the average chance, the return per $1 at the standard payouts (25x / 2x / 0.4x), and the
chance of a profit.

- **Put on my slip** replaces your entry slip with the lineup, so you can save it in My entries once
  it's played.

**Safer: a 3-pick Power of Goblins.** The best Goblins the model gives 75% or more.

- Up to November 20, 2026, Goblins the model gave 75%+ went over 82% of the time (182 of 222). It
  said 79%, so its Goblin chances have held up.
- All 3 hit about half the time. Goblins pay less, though. Your three Goblin-heavy entries
  worked out to $0.82-0.98 back per $1 at the model's chances.

**High risk: a 3-pick Power of Demons.** The best Demons the model gives 55% or more.

- Demons the model gave 55%+ went over 72% of the time (48 of 67, it said 61%).
- PrizePicks pays more for Demons, but all 3 have to hit, about 1 time in 4. It's fewer lines
  than the Goblins, so it's less sure.

Both use the same rules as Standard for who can be in them, but one pick per game, so the chance shown
for all of them hitting is honest. With only 2 such lines it's a 2-pick Power.

**What's it worth?** PrizePicks publishes no formula for what Goblins and Demons pay. So instead of a
return, the card shows the least the entry must pay to be worth it at the model's chances. That's 1
divided by the chance all of them hit: three Goblins at 80% need at least 1.96x. Build it on
PrizePicks and play it only if the payout it shows is at least that. The card also shows how Goblins
or Demons like these have done so far. A ⚠ warns when they've hit clearly less often than the model
said, since then the payout needed is higher than shown.

### What it handles for you

- Each card's team, opponent and game day are read from the page.
- The date is set from the day shown on the cards.
- Players listed **Out** on the official injury report are left out. **Questionable** ones are flagged.
- A card whose team doesn't match our data (a recent trade) is set aside.

### Goblins and Demons

- These "More-only" cards are listed separately, with the model's More chance. They aren't ranked,
  because they pay differently.
- Which kind each card is comes from PrizePicks' own tag in the copied page.
- The **All / Demons / Goblins** buttons show one kind at a time.

### Lines it sets aside

These are listed with the reason, rather than guessed:

- first-half, quarter and other part-game lines
- stats PrizePicks has that NBALine doesn't model
- names it doesn't know, or that match more than one player

### Games in progress

Lines whose game has started are followed live, every 15 seconds while the tab is open:

- his stat so far, the game clock, his pace, and a bar toward the line
- the model's **live chance**: its pre-game projection, updated with his stats so far, his minutes
  and the time left (`nbaline/pickem/ingame.py`)
- a live pick when one side reaches 54.2%
- "feed not answering" when NBA.com's live feed stops answering

The live chance was tested on Nov 10's games at the end of Q1, halftime and the end of Q3. It beat
both the pre-game chance and "he keeps his current pace", on one night so far.

---

## Check lines

Type a player, pick the stat, type the PrizePicks line, and press **Analyze**. You get:

- the model's chance of More and of Less
- the expected average and median
- injury news for both teams
- the reasons behind the prediction
- how often he went over this line in his last 10 games

### Looking back at a past game

Pick an earlier game date to see what the model would have said before tip-off.

- It uses only games before that date, plus that day's official injury report.
- Once the game is final, the card shows the actual number and whether the model was right (✓ or ✗).
- These checks don't count toward the model's record on Results, because you chose the lines after
  knowing how they turned out.

---

## My entries

### Build a slip

- Press **+ Add** on Best lines, or **+ More / + Less** on Check lines. The button turns green; click
  again to take the pick off. You can also add a pick by hand.
- Choose **Power** or **Flex** and type the amount.
- Check that the payouts match your PrizePicks app.
- The slip shows the model's chance of cashing and the expected return.
- Press **Save entry** for what you actually played.

### Profit boost promos

Type the boost's % (for example 30). PrizePicks adds it to the winnings above your entry fee:

| Payout | With a 30% boost |
|---|---|
| 7x | 8.8x |
| 1.25x | 1.325x |
| 0.4x (1x or less: boosted on the whole amount) | 0.52x |

Type payouts as PrizePicks shows them *before* the boost. Each box shows what it comes to with it,
and the entry is graded with it.

### Protected plays

- Tick **Protected play** for a PrizePicks protected play.
- If it loses outright, it stays in your record but is left out of profit and ROI.
- Anything it pays back counts as usual.
- You can also mark an entry as protected from its card after saving.

### Changing payouts after saving

**Payouts** on an open entry's card changes its payouts and boost. Use it, for example, for the
reverted payouts PrizePicks shows once a pick is removed. Its chances and payout update at once.

### Before the games

Each open entry shows:

- each player's jersey number (from NBA.com's player index)
- each pick's chance when you saved it, and now
- when each game starts

### During the games

Open entries follow the NBA's live box scores. They refresh every 15 seconds while the tab is open,
and at once when you come back to it.

Each pick shows:

- his stat so far, his minutes and the game clock
- how far it is from the line ("needs 2", "room for 1")
- a progress bar toward the line: white in play, green won, red lost, grey push or void
- a **Pace %** pill: where he finishes at his current rate, as a share of the line (4 of 5 at the
  buzzer = 80%). Green when on pace for your side, amber when behind.
- a red dot when his game is on, and a highlight when he's on the floor right now
- **✓ hit** or **✗ lost** the moment it's decided (More can't lose once he passes the line; Less can't win)

Each entry shows what's locked in and the most it can still pay.

If NBA.com's live feed stops answering, the picks keep the last numbers it sent and a note says so.
NBALine keeps trying, and the server window logs when it stopped and when it's back.

The **List / Grid** switch shows one entry per row or two side by side.

### Chances now

The **Chances now** dropdown under each open entry keeps the slip's numbers up to date:

- the chance of a profit, of any payout, and the average payout
- every amount it can still pay, with its chance ("5 of 6 · $2.29 · 22.7%")

Each pick counts with its chance now:

- before its game: its latest re-check
- during it: the live chance
- once decided: how it ended. After a miss, "6 of 6" is crossed out.

**Pushes:** a pick on a whole-number line can finish exactly on it. It then reverts, and the entry is
paid on one pick fewer. Amounts only a push leads to are marked "+1 push" ("4 of 4 · +1 push · $7.50").

Chances now assumes picks are independent, and that players still to come will play.

---

## Results

After the games, press **Update results**, or let the morning update do it.

### How entries are graded

Entries are graded the PrizePicks way. A pick **reverts** when the player doesn't play or finishes
exactly on the line. The entry is then paid from the reverted payouts for the picks left.

For a 6-pick Flex:

| Picks left | Pays |
|---|---|
| 5 | 10x / 2x / 0.4x |
| 4 | 6x / 1.5x |
| 3 | 3x / 1x |
| 2 | 3x |
| 1 | 1.5x |
| none | refund |

- A Power pays the smaller Power payout for the picks left. With one pick left it pays 1.5x if it
  hits, so a 2-pick Power with one revert pays 1.5x, not a refund.
- The slip shows this table under **If players revert**, editable like the payouts. Goblins and
  Demons change it.
- **If PrizePicks paid a different amount,** press **Edit** on that graded entry and type what it paid.
  Your record and profit use that amount from then on, and the card offers a button to go back.

### What Results shows

- Profit and ROI, and your pick hit rate.
- **Model vs. PrizePicks:** a Brier score. 0.250 is a coin flip; lower means the model's chances beat the lines.
- **Model's pick by stat** and **by how sure it was:** how often the model's side was right on
  standard lines, with the range the true rate is probably in, colored against break-even (54.2%).
  - A model worth following is right more often the surer it is. "Model was" says how far its chance
    ran above or below how often it was right.
  - Click a column of the by-stat table to sort it.
  - A stat gets a **trusted** badge after 10+ graded nights, once even the low end of its range is
    above break-even.

### Why it won or lost

Each graded entry opens to its picks, misses first, with what was different about his night:

- how unusual the night was ("his most rebounds in 20 games")
- his minutes against his usual, and why (foul trouble, a blowout, overtime, a close game)
- a fast or slow game
- for a combined stat, the part that rose most and the part that fell most
- hot or cold shooting, more or fewer shots, and his share of the team's shots
- where the line sat, when his last 10 games were clearly on one side of it
- otherwise, how his night compared with his usual ("A big night: 5 offensive rebounds (usually 2.2)")

The reasons are sorted by which way they pushed his number:

| | On a hit | On a miss |
|---|---|---|
| Pushed it the way it went | **Why it hit** | **Why it missed** |
| Pushed it the other way | **Worked against it** | **Helped, but not enough** |

So 32 minutes instead of his usual 22, on a Less that still hit, shows as luck, not as the reason it hit.

Also shown:

- how close it finished, and what the model expected
- picks that won or lost together, above the picks: several on one player, or players in the same game

It's worked out from the box scores with fixed rules (`nbaline/pickem/explain.py`), so it only says what
the numbers show. An injury during the game shows up as "only 14 min", without a reason.

### The chance adjustment

This corrects a model that's too sure of itself against PrizePicks.

- It learns one number from every graded standard line: how much of the model's lean to keep. With
  0.4, a 70% lean shows as 58%.
- It applies to standard lines only. Goblins, Demons and yes/no props are left alone.
- It switches itself on only after 10 graded nights, and only if it beat the model's own chances when
  tested night by night.
- Hovering a chance shows the model's own number. Saved checks always keep the model's own chance, so
  the adjustment never learns from itself (`nbaline/pickem/calibration.py`).

---

## Long shots

Pick a day and see the lines that hit even though the model gave them little chance.

- It covers every line you pasted or checked, on the side that won (Goblins and Demons only when they
  went over).
- Filter to Demons, Goblins or standard lines.
- Sort by the model's chance, lowest or highest first.
- Lines you played are marked.

---

## Update data & model

**⟳ Update data & model** (top right) does the whole refresh in one click:

1. Downloads the latest box scores.
2. Checks nothing is missing against the official schedule.
3. Grades your entries.
4. Retrains the points model and the 25 other stat models.

- It takes about 7 minutes on a day with new games, and under a minute when there's nothing new.
- A model with no new data to learn from is kept as it is.
- It runs in the background, so you can keep using the app. A banner shows each step.
- It's the same job as `python daily.py --retrain`.

---

## Things to know

- **Break-even per pick:** 2-pick Power 57.7%, 3-pick Power 58.5%, 5- or 6-pick Flex 54.2%. A "Lean"
  means the model is at least 54.2% on one side.
- **The median decides More vs. Less, not the average.** A few big nights pull a player's average up,
  but the median is his typical game. So a pick can say Less with "average 26.1, median 25.2" on a
  25.5 line.
- **Default payouts are typical values, not guaranteed.** PrizePicks changes them and they differ by
  state, so edit them to match your app.
- **Goblins and Demons change every payout** by amounts PrizePicks doesn't publish. Two one-Goblin
  6-pick Flexes paid 19.2x and 16.6x for 6 of 6. Copy those payouts from the app, reverted ones too.
  How PrizePicks pays is summed up at the top of `nbaline/pickem/payouts.py`.
- **Expected returns assume picks are independent.** Picks from the same game often move together.
- **Everything you paste is saved** in `data/prizepicks.db`: every line analyzed with its prediction,
  the board text (an identical re-paste is skipped), and your entries.
- **How lines are scored:** each player and stat counts once a day, at the last line you saw before
  tip-off, because PrizePicks moves lines during the day. Goblins and Demons are scored separately.
- **Your results grade the model; they don't train it.** It trains on every NBA game, which already
  includes yours.

---

## Data sources in detail

**Box scores** (stats.nba.com, through `nba_api`). Reliability: high.
- Official NBA stats.
- Games still in progress are skipped.
- Every team box score must add up to its players'. A download made as games finish can catch one side
  before the other: a team row that's behind is rebuilt from its players, and a game whose player rows
  are behind waits for the next download.
- Grades from the last 3 days are checked again when new box scores arrive, so a late stat correction
  fixes them too.
- `nba_api` is unofficial, so the NBA can change or rate-limit it.

**Which team a player is on** (his most recent game).
- Lags after a trade, until his first game with the new team.

**Opponent, home/away, tip-off** (official NBA schedule, `nbaline/schedule.py`). Reliability: high.
- A typed opponent or home/away that doesn't match the schedule is refused.
- Predictions made after tip-off are flagged.

**Who's out** (official NBA injury report PDF, `nbaline/injuries.py`). Reliability: high for what's filed.
- Out and Doubtful players are treated as out. Questionable ones are flagged.
- Teams update it every 15 minutes, so predict close to tip-off.
- Late scratches after the last report aren't caught.
- If no report covers the game yet, absences are **guessed** from recent games, and the output says so.

**Who's starting** (NBA.com's daily starting lineups, `nbaline/lineups.py`, 2023-24 on). Reliability: good.
- Starters are "Expected" during the day and "Confirmed" about 30 minutes before tip-off. Expected
  ones can still change.
- Each line shows tonight's role, plus a **Starting tonight** / **Bench tonight** tag when it isn't
  his usual role.
- The same file lists inactive players, shown as **Inactive tonight**. It catches some late scratches
  the injury report misses.
- The models use tonight's role once it's posted, and leave it blank until then (`TRAINING.md` 4e).
- It's an unofficial file. Without it, the models go by how often each player has started lately.

**Player tracking** (NBA.com's camera-tracking stats, `nbaline/tracking.py`, 2017-18 on). Reliability: good.
- Checked against the box scores: the same players, and every assist count matched.
- NBA.com has none for 16 of 1,469 game days (mostly the 2020 restart).
- Used only by the 6 stats where it tested better: Turnovers, Rebounds, Offensive Rebounds,
  Rebs+Asts, Two Pointers Made and Free Throws Attempted (`TRAINING.md` 4f).
- NBA.com has changed how it counts several of these. From 2024-25, the same players show about 50% more
  drives and 80% more time holding the ball. Rebound chances also ran 30% low from Nov 2025 to Mar 23, 2026.
  So each game is measured against the league's rate that night: 1.0 means league average (`TRAINING.md` 4h).
- If a day's download fails, the inputs use his other recent games.

**Shot profile and dunks** (NBA.com's shot charts, `nbaline/shots.py`, 2017-18 on). Reliability: high.
- Every shot with its zone, distance and type.
- Checked against the box scores: each player's zone attempts plus half-court heaves add up to his
  field-goal attempts, and his makes match in 99.9% of games.
- Used by the 10 stats where it tested better: FG, 3-PT and two-point attempts, free throws made and
  attempted, PRA, steals, blocks, blocks+steals and defensive rebounds (`TRAINING.md` 4g).
- Downloaded with the box scores: this season every run, a month per request. If it fails, the last
  saved copy is used.

**Hustle stats** (NBA.com's hustle stats, `nbaline/hustle.py`, 2017-18 on). Reliability: fair.
- Deflections, contested 2s and 3s, screen assists, loose balls and box outs, logged by people at each game.
- Their counting has shifted over the years (deflections +15% from 2024-25, contested shots down 40%
  since 2017-18), so each game is measured against the league's rate that night, like tracking.
- Box outs are used only from 2022-23: before that every box out was logged, not just the ones that won
  the ball. Charges drawn are left out: too rare, and arenas log them very differently.
- Used by the 6 stats where they tested better: Steals, Blocked Shots, Blks+Stls, Offensive Rebounds,
  Dunks and Free Throws Attempted (`TRAINING.md` 4i).

**PrizePicks lines.** You paste or type them. Lines move during the day, so use the number you can
actually play.

---

## Command line

### Daily use

```bash
python fetch_data.py                                       # 1. latest games (~30 s)
python -m nbaline.schedule                                 # 2. tonight's games and tip-off times
python -m nbaline.injuries --team GSW                      #    (optional) the official injury report
python predict.py "Stephen Curry" 28.5                     # 3a. one line (opponent comes from the schedule)
python predict.py --slate slate.csv                        # 3b. or a whole slate
python fetch_data.py && python score.py                    # 4. after games: grade everything
```

**predict.py options:**
- Who's out comes from the injury report. A player listed Out or Doubtful is refused, with the reason.
- `--out "Name"` adds someone the report doesn't have yet (a late scratch you saw on X, for example).
- `--date 2026-11-11` predicts a future game. If his team doesn't play that day, it says when they do.
- `--no-schedule --opp BOS --home` tries a matchup that isn't on the schedule.
- `--over-odds -120 --under-odds +100` uses the real prices (default -110 each way).
- Slate CSV columns: `player,line,over_odds,under_odds,out` (several outs separated by `;`). The lines
  in `slate_example.csv` are placeholders.

**Grading:** every prediction is saved to `predictions_log.csv`. `score.py` grades it: projection
error, calibration, record and profit, and model vs. sportsbook Brier score. Judge that after about
300 lines, not 30.

**Retraining:** `python train.py` (points, about 2 minutes) and `python stat_models.py --train` (the
other stats, about 5 minutes). `daily.py --retrain` does both. Each retrain reuses the parts that only
depend on past seasons, so it gives the same models as a full retrain in about half the time
([TRAINING.md §7](TRAINING.md#7-retraining-faster-with-the-same-models)).

### The automatic morning update

`daily.py` runs the whole morning routine:

1. Downloads last night's box scores (up to 3 tries if the NBA site fails).
2. Checks every finished game on the official schedule is in the data.
3. Grades yesterday's predictions and PrizePicks entries.
4. Retrains the models once a week, but only if the data is complete.

It writes a log to `logs/daily_YYYY-MM-DD.log` and a summary to `data/status.json`.

To run it every morning at 9:00 with Windows Task Scheduler (once, in PowerShell). If the computer was
off, it runs as soon as it's back on:

```powershell
$a = New-ScheduledTaskAction -Execute "$PWD\.venv\Scripts\pythonw.exe" -Argument "daily.py" -WorkingDirectory "$PWD"
$t = New-ScheduledTaskTrigger -Daily -At 9am
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "NBALine daily update" -Action $a -Trigger $t -Settings $s
```

To remove it: `Unregister-ScheduledTask -TaskName "NBALine daily update"`.

**Safety net:** `predict.py` checks the data against the schedule every time. It prints a big
**DATA IS OUT OF DATE** warning if a finished game is missing, and warns if the model is over 10 days old.

---

## Changing the web page

The page is a React + TypeScript app in `frontend/`. NBALine serves the built copy in `frontend/dist`,
so using the app needs only Python. After editing anything in `frontend/src`, rebuild it (needs
[Node.js](https://nodejs.org) 22+):

```bash
cd frontend
npm install        # once
npm run build      # type-checks, then writes frontend/dist; an open page offers to refresh
```

While working on the page, `npm run dev` serves it at http://localhost:5173 with instant reloads, and
passes `/api` calls to a running NBALine.
