# How the model was trained, and the ways to make a model better

This is the record of how NBALine's model was built: every technique tried, how it was scored, and what actually helped. It doubles as a reference for the different ways to "tune" a model.

---

## 1. Scoring: how we know a change really helps

You can't improve what you can't measure, so the scoring harness came first ([nbaline/evaluate.py](nbaline/evaluate.py), [experiments.py](experiments.py)).

### Walk-forward testing (no peeking at the future)

Each test trains only on the past and predicts the next season, like using the model for real:

| Fold | Train on | Test on |
|---|---|---|
| 2022 | 2017-18 … 2021-22 | 2022-23 |
| 2023 | 2017-18 … 2022-23 | 2023-24 |
| 2024 | 2017-18 … 2023-24 | 2024-25 |
| **Holdout** | everything before | **2025-26 and 2026-27** (only used once, at the very end) |

Every decision below was made on the three tuning folds. The holdout was kept untouched until the end. Otherwise we would slowly "tune to the test" and fool ourselves.

### The scores

| Metric | What it measures | Good value |
|---|---|---|
| **CRPS** (main score) | Grades the *whole* predicted distribution, i.e. every possible line at once. It rewards being close **and** being honestly confident. Measured in points. | Lower |
| MAE | Average miss of the single projection, in points | Lower |
| COV80 | How often the real score landed in the model's 10th–90th percentile range | ≈ 80% |
| Brier / LogLoss | Quality of the over/under probability on a specific line | Lower |
| ECE (calibration) | Average gap between "said 60%" and "happened X%" | ≈ 0 |

### Is the difference real or luck?

Two models are compared **on the exact same games**, and the per-game differences are bootstrapped (resampled 1,000 times) into a 95% confidence interval. If the interval doesn't cross zero, the difference is real. Many changes that "looked better" turned out to be noise, and we didn't keep those.

```bash
python experiments.py --compare E2 B1
# B1 vs E2: CRPS change -0.0060  95% CI [-0.0088, -0.0032]  -> B better (real)
```

### A trap to avoid: accuracy against fake lines

We have no historical sportsbook lines yet, so line tests use synthetic ones (a player's recent average rounded to .5). The model is right ~62% of the time against those, but **that number is inflated**. Points are skewed: a player usually scores *below* his average, with occasional big nights pulling the average up. Only 46% of games went over the average-based line, so a model that knows about the skew wins easily. Real books set lines near the *median*, not the average. Only real lines (see [score.py](score.py)) can tell us the true win rate.

---

## 2. The ways to improve a model, and what each did here

"Fine-tuning" gets used loosely. These are the actual levers, roughly from most to least useful in this project:

| Lever | What it is | Result here |
|---|---|---|
| **Better inputs (features)** | Give the model information it didn't have: minutes trends, rates per minute, team strength gaps, absences on both teams | **Biggest win** (−0.009 CRPS, real) |
| **Better loss function** | What the model is trained to minimize. *Poisson* loss fits count data like points, where big scorers vary more. | Real gain (−0.005) |
| **Ensembling** | Average two different model types (XGBoost + neural net) whose mistakes differ | Real gain (−0.003). The 70/30 blend beat 50/50. |
| **More data** | Ten seasons instead of five | Small gain |
| **Epochs / boosting rounds + early stopping** | Train round after round and watch error on an unseen season; stop where it bottoms out | Small gain, and it picks the round count automatically |
| **Feature removal (ablation)** | Remove each group and see if the score drops | The "matchup" group added noise, so it was removed |
| **Uncertainty model** | A second model predicts how *volatile* this player-game is (some players are streakier) | Better calibration, small CRPS gain |
| **Hyperparameter search (Optuna)** | Automated search over tree depth, regularization and so on: 30 trials, Bayesian optimization | **No real gain.** The defaults were already near the best. |
| **Lower learning rate** | Smaller steps, more rounds | No real gain |
| **Fine-tuning on recent data** | Train on all seasons, then add extra trees fit only on the newest season (the classic "fine-tune" idea) | No real gain |
| **Recency weighting** | Count recent seasons more | Made it **worse** (half-life 2 seasons) |
| **Neural net alone** | 2-layer network trained in epochs | **Worse** than XGBoost (tables of numbers favor trees), but useful inside the blend |

**Lesson:** knobs (hyperparameters, learning rates, fine-tuning tricks) moved almost nothing. Information (features) and the right loss function moved the most. That is typical for this kind of data.

### What "epochs" look like

XGBoost adds one tree per round. Here is error on training data vs. a season it never saw ([learning_curve.py](learning_curve.py)):

```
round   train MAE   unseen MAE
   50       5.401       5.525
  200       4.792       4.947
  500       4.725       4.916
 1500       4.628       4.912   <- best
 3000       4.508       4.919   <- still improving on training data, getting worse on new games = overfitting
```

The neural net is the same idea with epochs (full passes over the data). It peaked at epoch 21, and early stopping halted it 8 epochs later.

### Why we don't fine-tune an LLM for this

LLM fine-tuning teaches a language model new *text behavior*. Here the job is predicting a number from a table of stats, and a 2 MB tree model trained in seconds beats a billion-parameter language model at it. LLMs fit on top: explaining picks in plain English, or reading injury news.

---

## 3. The full journey (tuning folds, CRPS: lower is better)

| Step | Experiment | CRPS | MAE |
|---|---|---|---|
| Last-10 average (no ML) | `base_l10` | 3.677 | 5.11 |
| Recent-weighted average (no ML) | `base_ewm` | 3.616 | 5.02 |
| Original prototype | `E0` | 3.528 | 4.89 |
| + early stopping | `E1` | 3.524 | 4.88 |
| + all 10 seasons | `E2` | 3.518 | 4.88 |
| + Poisson loss + volatility model | `B1` | 3.512 | 4.87 |
| + new features | `E5_v2` | 3.503 | 4.86 |
| − matchup group | `E5_v2_minus_matchup` | 3.502 | 4.86 |
| + tuned hyperparameters | `E6_tuned` | 3.502 | 4.86 |
| **+ 30% neural-net blend** | **`FINAL`** | **3.498** | **4.85** |

## 4. Final exam: holdout seasons (never used for any decision)

| Model | CRPS | MAE | Calibration error |
|---|---|---|---|
| Recent-weighted average | 3.621 | 5.03 | 1.1% |
| Original prototype (`E0`) | 3.499 | 4.86 | 1.4% |
| **FINAL** | **3.478** | **4.83** | 1.2% |

FINAL vs. the prototype: −0.020 CRPS, 95% CI [−0.026, −0.015], so the improvement is real.

**Calibration on 2025-26** (line = recent-weighted average):

| Model said | Actually happened | Lines |
|---|---|---|
| 25.0% | 24.5% | 1,005 |
| 36.0% | 37.2% | 4,394 |
| 47.6% | 46.7% | 4,123 |
| 57.3% | 55.9% | 2,064 |
| 63.8% | 63.5% | 1,631 |
| 75.4% | 73.4% | 436 |

When the model says 64%, it happens about 64% of the time. Those probabilities can be compared directly to a sportsbook's odds.

## 4b. The other PrizePicks stats (`stat_models.py`)

Each stat gets its own model, built the same way as the points model:
- **Recipe:** Poisson XGBoost with the tuned settings and early stopping, trained on ten seasons.
- **Inputs:** that stat's own history (last 3/5/10/20/40 games, recent-weighted averages, spread, season and per-minute rates) plus the shared context (minutes, rest, absences, opponent).

**How each stat was tested:**
1. **Choosing the uncertainty method.** On the 2023-24 and 2024-25 tuning folds, each stat picked between the volatility model and a negative-binomial count distribution. The choice was by Brier score on lines set at the player's recent-weighted average, among the methods whose calibration error on those seasons was 0.03 or less.
2. **One holdout test.** The 2025-26 season was then scored once with that choice.
3. **The bar for passing:** beat the no-model baseline (the recent-weighted average with the same kind of uncertainty) **and** have a calibration error of 0.03 or less.

**The count distribution's spread follows the projection.** A negative binomial has variance = mean + alpha × mean². At first one alpha was fitted for every player, which gave big projections too much spread and small ones too little: the best alpha for the top third of projections was 2–5 times smaller than for the bottom third, in every stat. Now alpha(mean) = exp(a + b·ln(mean)), with a and b fitted by maximum likelihood on the validation season (`modeling.fit_count_spread`). The fitted b is close to −1, which means the variance is roughly proportional to the mean.

"Off-line calibration" below is the calibration error on lines 2 below and 2 above the usual one, where Goblin and Demon lines sit. It checks the spread, not just the middle.

| Stat | Uncertainty | Avg miss (model / baseline) | Brier (model / baseline) | Calibration error | Off-line calibration |
|---|---|---|---|---|---|
| Rebounds | count dist. | 1.95 / 2.00 | **0.2373** / 0.2456 | 0.5% | 1.0% |
| Assists | volatility | 1.45 / 1.48 | **0.2363** / 0.2431 | 1.1% | 1.1% |
| 3-PT Made | count dist. | 0.97 / 0.98 | **0.2142** / 0.2198 | 1.8% | 1.4% |
| Steals | count dist. | 0.77 / 0.79 | **0.2293** / 0.2386 | 0.5% | 0.3% |
| Blocked Shots | count dist. | 0.56 / 0.55 | **0.1932** / 0.2003 | 1.0% | 0.5% |
| Turnovers | count dist. | 0.95 / 0.98 | **0.2298** / 0.2412 | 0.5% | 0.6% |
| Pts+Rebs+Asts | count dist. | 6.19 / 6.45 | **0.2365** / 0.2502 | 1.0% | 1.0% |
| Pts+Rebs | count dist. | 5.71 / 5.92 | **0.2371** / 0.2499 | 1.1% | 1.2% |
| Pts+Asts | volatility | 5.28 / 5.49 | **0.2373** / 0.2489 | 0.6% | 0.8% |
| Rebs+Asts | count dist. | 2.70 / 2.77 | **0.2386** / 0.2482 | 1.0% | 1.2% |
| Blks+Stls | count dist. | 0.98 / 1.01 | **0.2307** / 0.2392 | 0.6% | 0.5% |
| Fantasy Score | volatility | 7.88 / 8.20 | **0.2375** / 0.2490 | 1.2% | – |
| FG Attempted | count dist. | 2.83 / 2.97 | **0.2340** / 0.2485 | 0.9% | 0.9% |
| FG Made | count dist. | 1.85 / 1.92 | **0.2357** / 0.2467 | 0.7% | 0.7% |
| 3-PT Attempted | count dist. | 1.59 / 1.62 | **0.2230** / 0.2305 | 2.3% | 1.9% |
| Free Throws Made | count dist. | 1.49 / 1.51 | **0.2313** / 0.2388 | 2.2% | 1.2% |
| Free Throws Attempted | volatility | 1.79 / 1.81 | **0.2385** / 0.2419 | 1.1% | 2.7% |
| Offensive Rebounds | count dist. | 0.89 / 0.91 | **0.2286** / 0.2365 | 0.8% | 0.6% |
| Defensive Rebounds | count dist. | 1.62 / 1.66 | **0.2372** / 0.2451 | 0.6% | 0.9% |
| Two Pointers Made | count dist. | 1.48 / 1.53 | **0.2335** / 0.2435 | 0.7% | 0.4% |
| Two Pointers Attempted | count dist. | 2.07 / 2.17 | **0.2324** / 0.2461 | 0.9% | 0.8% |
| Personal Fouls | count dist. | 1.10 / 1.13 | **0.2364** / 0.2434 | 2.2% | 0.4% |
| Double Doubles | yes/no chance | 0.13 / 0.13 | **0.0635** / 0.0669 | 1.0% | – |
| Triple Doubles | yes/no chance | 0.01 / 0.01 | **0.0055** / 0.0057 | 0.1% | – |
| Dunks | count dist. | 0.49 / 0.49 | **0.1595** / 0.1656 | 0.4% | 0.4% |

**All 25 passed.**
- **Which method won:** with the spread following the projection, the count distribution wins for almost every counting stat, including the big sums (Pts+Rebs+Asts, Pts+Rebs) and shot attempts that used to prefer the volatility model. Assists, Pts+Asts and fantasy score use the volatility model.
- **Free throws are the hard case.** Free throws come in pairs, which no simple count distribution describes well. For attempts, the count method scores better (Brier 0.2366 vs. 0.2385) but runs about 3 points low at the usual line in all three seasons, so it isn't eligible; the volatility model is used, and its off-line calibration (2.7%) is the weakest in the table. Free throws made uses the count method (2.2% at the usual line).
- **Closest to the 3% limit:** 3-PT attempted (2.3%), free throws made (2.2%) and personal fouls (2.2%).
- **One soft spot:** on blocks, the average miss is a hair worse than the baseline, but the over/under probabilities are still better, and those are what matter for PrizePicks.
- **How big the gains are:** from 0.003 (free throw attempts) to 0.014 Brier against lines at the recent average, most of them 0.006–0.013. Real PrizePicks lines are sharper than that, so the real edge will be smaller. The Results tab is where that gets measured.

**Dunks, double-doubles and triple-doubles** were added later, built and tested the same way, with these differences:
- **Dunks** aren't in box scores. `fetch_data.py` counts made dunks from each season's shot chart (every shot has a type, like "Alley Oop Dunk Shot"). The chart is downloaded a month at a time, because it stops at about 100,000 shots per request.
- **Double- and triple-doubles** are 1 or 0 each game. So they use a logistic model whose output *is* the chance, instead of a count distribution. They also see the player's rebounds, assists, blocks and steals history, since a double-double takes two stats at once.
- **A harder check.** Most rotation players almost never record a double-double, which makes the overall Brier easy to win. So the 2025-26 holdout was also scored on just the players who'd get these lines:
  - **Double-doubles** (players at a 20%+ rate): 0.1953 vs. 0.2058 baseline. Calibration was exact in 2024-25 but about 4 points high in 2025-26, when double-doubles were rarer league-wide (9.0% vs. 10.0% expected).
  - **Triple-doubles** (5%+ rate): 0.0854 vs. 0.0890.
  - **Dunks** (1+ per game): 0.2178 vs. 0.2259, and well calibrated in both seasons.

**The shooting splits and fouls** (FG, 3-PT and 2-PT attempts and makes, free throws, offensive/defensive rebounds, personal fouls) were trained untested at first and tested afterwards with the same procedure; all 10 passed (table above).

## 4c. Free inputs from analysts' reasoning (`E9_*` experiments)

Betting previews argue things like the following. Each idea was turned into an input built only from free data we already download (no betting lines):
- "He sat the 4th quarter of two blowouts, so expect full minutes tonight" became **minutes in close games** (final margin of 10 or less) and the **share of recent blowouts**.
- "He scores 35 per 36 without Holmgren and Williams" became **player-specific splits without tonight's absent teammates**: extra minutes, points, shots, rebounds and assists per minute in past games when the same teammates sat, plus how many such games there were.
- "Portland gives up free throws" became **what each defense allows** per 100 possessions: free throws, 3-pt attempts and assists allowed, turnovers forced, and the share of offensive rebounds given up.

**Points model** (XGBoost, 2022–24 tuning seasons, paired test against the same recipe without them):

| Added | CRPS change | Verdict |
|---|---|---|
| Close-game minutes | +0.0003 | no real difference |
| Splits without absent teammates | +0.0006 | no real difference |
| What the opponent allows | +0.0019 | **worse** (real) |
| All three | +0.0003 | no real difference |

**Other stats** (over/under Brier, 2023-24 and 2024-25 seasons, same comparison):

| Stat | Brier old → new | Verdict |
|---|---|---|
| Assists | 0.2351 → 0.2347 | **better** (real) |
| Turnovers | 0.2319 → 0.2313 | **better** (real) |
| Free throws made | 0.2321 → 0.2318 | **better** (real) |
| Rebounds | 0.2375 → 0.2373 | no clear difference |
| Pts+Rebs+Asts | 0.2377 → 0.2376 | no clear difference |

**Decision:**
- **Points:** keeps its inputs. Its existing minutes, absence and defense inputs already carry this information.
- **The 22 other stat models:** get the new inputs. Every tested stat moved the right way, and the opponent-specific ones (assists allowed, turnovers forced, free throws allowed) helped the stats they describe.

**The lesson:** an argument that sounds sharp in a preview usually describes something the model already sees in another form. The gains came where the input matched the stat directly.

## 4d. Review: looking for mistakes (November 2026)

A full pass over the data, the inputs, the training code and the app, with a numeric test for each
suspicion. These checks used the 2025-26 season, so read them as diagnostics, not as new test scores.

**What checked out**

| Check | Result |
|---|---|
| Raw data | No duplicate rows, no missing games, every game has two teams. Player points, assists and shots add up to the team totals in all 21,806 team-games. |
| Leaks (inputs that "see the future") | None. For 126 past player-games, the inputs were rebuilt the way the app does it (only games before that date, told who sat). All 103 inputs the models use matched the training inputs exactly. |
| "Real or luck" verdicts | Players in the same game share its luck, so the bootstrap was redone resampling whole nights instead of single player-games. All 13 verdicts stayed the same. |
| Injury report reading | This season the last report before tip-off listed 241 rotation players Out or Doubtful and all 241 sat. Of players not listed, 3% sat. The report knew 77% of all absences. |

**What was wrong, and the fix**

| Problem | Evidence | Fix |
|---|---|---|
| The app built inputs from only the last two seasons; training used a player's whole history. | "Last 40 games" and long-run averages differed for players who had missed a lot of time (e.g. 7.2 vs. 6.0 points). | The app now keeps three seasons, plus the whole history of the players being predicted (`predictor.predict_requests`). |
| With no injury report, a player counted as out only after missing 3 team games in a row. That misses most absences, and the models then treat the team as full strength and project too low. | Points CRPS knowing exactly who sat 3.489; guessing after 3 missed 3.554 (calibration error 4.2%); after 2 missed 3.542; **after 1 missed 3.524 (2.2%)**. No model at all: 3.610. | `features.GUESS_OUT_AFTER = 1`. |
| Bench players (under 15 minutes a game) are scored by models that never trained on them. | On 8-15 minute players the calibration error was 7.0%, against 0.8% for everyone else. About 2% of the players on pasted boards. | The app marks them "low minutes" and treats their lines as less reliable (`features.MIN_TESTED_MINUTES`). |
| Pushes on whole-number lines. Landing exactly on a line like "4 assists" is a push (PrizePicks removes the pick), but the count models counted it as a Less win. Every test used .5 lines, so it never showed up there. | Typical whole-number lines push 15-22% of the time (assists 22%, rebounds 16%). Less looked 5-7 points better than it was (Kris Dunn Less 4: shown 65.3%, really 58.1%), More 5-7 points worse. 317 of the first 1,966 saved lines were on whole numbers. | `Pipeline.outcome_chances`: More and Less are now chances among the outcomes that aren't a push, and the push chance is shown separately. On .5 lines nothing changes (checked: identical to the old numbers). |
| The injury report's "not yet submitted" list was read per team, but a report covers several days. In the evening it lists tomorrow's games, where most teams haven't submitted yet, so tonight's late games looked unsubmitted. | For OKC @ POR (11 PM ET) the app skipped tonight's 10:45 PM report for both teams and fell back to an older report, up to 24 hours old. | `.nys` files now record the game for each "not submitted" (`injuries.py`), and `predictor._injury_info` only waits for teams that haven't submitted for that game. Old cached reports are re-downloaded once. |
| The count models used one spread setting for every player. | The best setting for the top third of projections was 2–5 times smaller than for the bottom third, in every stat. | The spread now follows the projection (section 4b). All 22 count stats were re-tested and retrained: Brier better in 16, the same in 4, worse in 2 (by 0.0002 or less); off-line calibration averages 0.9%. Biggest gain: free throws made, 0.2342 to 0.2313. |

**How much the published scores overstate real use.** The tests know exactly who sat out; before a game
you only know what the injury report says. Hiding absences at the rate the report really misses them
(28%, or 8% once a player has missed 3+ games) moves points CRPS from 3.489 to 3.504, about an eighth
of the model's edge over no model. Rebounds Brier goes 0.2375 to 0.2380, assists 0.2364 to 0.2367.
Calibration stays near 1%. So with a report, real use is close to the test; without one it is not.
Retraining on absences "as known before the game" was tried and made no real difference
(CRPS −0.0016, 95% CI [−0.0043, +0.0011]), so the models still train on who actually sat.

**Tried and rejected**

- **Stopping training on Poisson loss instead of average miss.** The models are trained with Poisson
  loss but stop adding trees when the average miss on an unseen season stops improving. Stopping on
  Poisson loss changed nothing: points CRPS −0.0003 (inside the noise) in each of three seasons,
  rebounds Brier identical.
- **With a report, also assuming out anyone unlisted who missed his last 2–4 games.** More wrong calls
  than right ones (of 14 such players, 4 sat).

**Found but not changed yet**

- **Who counts as a "rotation player".** Anyone averaging 20+ minutes over his last 10 games, including
  games from last season. That lets in fringe players who then sit by coach's decision: 54 of this
  season's 326 "absences" were unlisted players like that. They are noise in the absence inputs.
- **Players out since before the season began** are never counted as missing, because candidates come
  only from this season's games. It matters for a team's first 10 or so games.
- **Playoffs aren't downloaded.** From mid-April the models would be predicting playoff games from
  regular-season data only.

## 4e. Starting lineups (`E10_lineups`, November 2026)

**The data.** NBA.com's "Today's Starting Lineups" page reads one free file per day, with each team's
five starters marked "Expected" during the day and "Confirmed" about 30 minutes before tip-off
(`nbaline/lineups.py`). Files exist from the first night of 2023-24: 513 game days, 3,886 of the 3,887
games in our box scores, a known role for 99.5% of player-games. A player can be listed twice (expected
starter, then again on the confirmed roster before the confirmed lineup is out); 44 such rows were read
wrong at first and are fixed (`lineups.one_row_each`).

**The inputs** (`features.LINEUPS`): starting tonight (1/0, blank if not posted), share of his last 10
games started, the role change (tonight minus that share), his minutes in tonight's role over his last
20 games, and that minus his recent minutes. Before 2023-24 they're blank, so only the 2024 fold and
the holdout seasons can learn from them.

The signal is real before any model sees it:

| 2023-24 on | Player-games | Minutes, last 10 | Minutes that night | Role input says |
|---|---|---|---|---|
| Starting, usually bench | 3,533 | 22.0 | 28.4 | +6.2 |
| Bench, usually starts | 2,326 | 26.6 | 20.6 | −5.7 |
| Usual role | 58,166 | 26.6 | 26.0 | −0.4 |

**Points model** (XGBoost, `E6_tuned` vs. `E10_lineups`, paired, 95% intervals resampling whole nights):

| Season | CRPS | Change | Verdict |
|---|---|---|---|
| 2024-25 (tuning) | 3.5205 → 3.4962 | −0.0243 [−0.0303, −0.0184] | **better** (real) |
| 2025-26 (holdout) | 3.4920 → 3.4690 | −0.0230 [−0.0290, −0.0168] | **better** (real) |
| 2026-27 so far | 3.4092 → 3.3815 | −0.0277 [−0.0411, −0.0143] | **better** (real) |

That's about four times the largest earlier gain from an input. Over/under accuracy at the player's
recent average went from 58.5% to 59.5% (2024) and 58.7% to 59.6% (holdout). The real points model
(70% XGBoost, 30% neural net) gains the same on 2025-26: 3.4885 → 3.4662, −0.0223 [−0.0287, −0.0159].

**Before tonight's lineup is posted** the role inputs are blank. Does that cost anything? (2025-26)

| Role inputs | Points blend CRPS change | Rebounds Brier change |
|---|---|---|
| Known (posted lineup) | −0.0223, better (real) | −0.0012, better (real) |
| Blank (not posted yet) | +0.0027 [−0.0002, +0.0052], no clear difference | −0.0001, no clear difference |
| Assume his usual role | **+0.0254, worse** (real) | **+0.0016, worse** (real) |

So the role stays blank until it's posted. Guessing the usual role is right in only 85% of games, and
the misses are exactly the role changes that matter. Training with the role hidden on a random 30% of
rows (to learn the "not posted" case) made no difference (−0.0233 known, −0.0003 blank).

**Other stats** (each stat's final settings with vs. without, 2024-25 and 2025-26, over/under Brier at
the usual line, `python stat_models.py --ab lineups`): 21 of 25 better (real), 3 no clear difference,
1 worse.

| Stat | Brier old → new | Verdict |
|---|---|---|
| Fantasy Score | 0.2380 → 0.2346 | **better** (real) |
| FG Attempted | 0.2340 → 0.2308 | **better** (real) |
| Pts+Rebs+Asts | 0.2370 → 0.2340 | **better** (real) |
| Pts+Asts, Pts+Rebs | 0.2378 → 0.2351, 0.2378 → 0.2352 | **better** (real) |
| Rebs+Asts | 0.2383 → 0.2358 | **better** (real) |
| 3-PT Attempted, FG Made | 0.2235 → 0.2212, 0.2363 → 0.2343 | **better** (real) |
| Rebounds, Assists | 0.2369 → 0.2352, 0.2352 → 0.2336 | **better** (real) |
| Two Pointers Attempted / Made, Defensive Rebounds | −0.0017, −0.0015, −0.0016 | **better** (real) |
| 3-PT Made, Blks+Stls, Personal Fouls, Steals, Turnovers, Off. Rebounds, Double Doubles, Dunks | −0.0011 to −0.0002 | **better** (real) |
| Blocked Shots, Free Throws Attempted, Free Throws Made | −0.0001 to +0.0002 | no clear difference |
| Triple Doubles | 0.0058 → 0.0059 | worse (real, tiny) |

Calibration stayed under the 3% limit for every stat (the largest: Personal Fouls 2.3%).

**Decision:** the points model and every stat model except triple-doubles use the lineups
(`recipes.points_recipe`, `features.NO_LINEUPS`). `models/stats.json` still lists each stat's holdout
scores from before; this table has the new ones.

**Caveat:** every test used the starters who actually started. Earlier in the day the app sees the
"Expected" lineup, which can still change (a late scratch). NBA.com's old files keep only the final
lineup, so how often an expected lineup was wrong can't be measured from history.

## 4f. Player tracking (`E11_tracking`, November 2026)

An outside review argued that box scores show what a player produced, not the chances he had: 3 assists
from 9 passes that led to shots is a different night from 3 from 3. NBA.com's camera tracking counts those
chances, and its tracking dashboards can be asked for a single day, which gives each player's numbers for
that day's game (`nbaline/tracking.py`). Every game day since 2017-18 was downloaded: 1,453 of 1,469 (none
exist for the 2020 restart, Aug 1–14, and two single days), 98.9% of 15+ minute games. Checked against our
box scores: the same players, and every assist count matched.

**13 inputs** (`features.TRACKING`), per minute over his last 10 tracked games: potential assists, passes,
rebound chances (all, offensive, defensive), drives, free throws from drives, touches, paint touches and
time holding the ball; and over his last 20: assists per potential assist, rebounds per rebound chance and
turnovers per 100 touches. The app builds them exactly as training does (checked: identical for last
night's players).

**Points:** no clear difference either way.

| Test | CRPS | Change, 95% interval |
|---|---|---|
| XGBoost, 2022-23 to 2024-25 (vs. `E10_lineups`) | 3.4948 → 3.4950 | +0.0002 [−0.0017, +0.0020] |
| Real model, 2025-26 and 2026-27 so far | 3.4529 → 3.4522 | −0.0007 [−0.0034, +0.0021] |

**Other stats** (`python stat_models.py --ab tracking`, over/under Brier at the usual line, resampling whole
nights): decided on 2023-24 + 2024-25, then checked once on 2025-26.

| Stat | 2023-25 | 2025-26 check |
|---|---|---|
| Turnovers | 0.2314 → 0.2306, **better** (real) | 0.2292 → 0.2281, **better** (real) |
| Offensive Rebounds | 0.2286 → 0.2279, **better** | no clear difference (−0.0001) |
| Rebs+Asts | 0.2368 → 0.2362, **better** | no clear difference (−0.0005) |
| Rebounds | 0.2362 → 0.2356, **better** | no clear difference (0.0000) |
| Two Pointers Made | 0.2340 → 0.2337, **better** | no clear difference (0.0000) |
| Free Throws Attempted | 0.2367 → 0.2365, **better** | no clear difference (+0.0002) |
| 17 others, PRA, Pts+Rebs and Fantasy Score among them | no clear difference | |
| Pts+Asts | 0.2366 → 0.2369, **worse** (real) | |
| Assists | 0.2340 → 0.2347, **worse** (real), calibration error 3.4% (over the 3% limit) | |

Saved as `experiments/stat_ab_tracking_tune.csv` and `stat_ab_tracking_2025.csv`.

**Decision:** the 6 stats that tested better use tracking (`features.WITH_TRACKING`); Points and the other
19 stats keep their inputs. The daily update downloads each new game day's tracking (4 small requests).

**The lesson again (4c):** potential assists were the input expected to help assists most, and they made
assists worse: assists per minute and usage already carry it. Tracking helped where it counts something the
box score doesn't: rebound chances for the rebounding stats, touches for turnovers. The gains are a quarter
to a half of what starting lineups gave, and the scoring stats, the model's weakest against real PrizePicks
lines, gained nothing.

## 4g. Shot profile (`E12_shots`, November 2026)

The same outside review suggested where and how a player shoots: at the rim or from midrange, corner or
above-the-break 3s, pull-ups or catch-and-shoot. NBA.com's shot chart lists every shot with its zone,
distance and type, and the download for counting dunks already fetched it. `nbaline/shots.py` now keeps
the rest, summed per player per game, for every game since 2017-18. Checked against our box scores: each
player's zone attempts plus half-court heaves add up to his field-goal attempts, his makes match in 99.9%
of games, and the dunk counts are identical to the old download.

**10 inputs** (`features.SHOTS`):

- Over his last 10 games, per minute: shots at the rim, other paint shots, midrange shots, corner 3s,
  above-the-break 3s, and self-created jumpers (pull-ups, step-backs, fadeaways, turnarounds). Plus his
  average shot distance.
- Over his last 20: his shooting at the rim, the points per shot his zones would score at league-average
  accuracy, and how far above or below that he actually shot ("shot-making").
- League accuracy in each zone is taken over the year before each game day, so it never uses the game
  itself or anything after it.

Checked by hand for James Harden (Jan 2019), and the app builds exactly the same inputs as training.

**Points:** no clear difference either way.

| Test | CRPS | Change, 95% interval |
|---|---|---|
| XGBoost, 2022-23 to 2024-25 (vs. `E10_lineups`) | 3.4948 → 3.4935 | −0.0013 [−0.0031, +0.0002] |
| Real model, 2025-26 and 2026-27 so far | 3.4520 → 3.4510 | −0.0010 [−0.0035, +0.0016] |

**Other stats** (`python stat_models.py --ab shots`, over/under Brier at the usual line, resampling whole
nights): decided on 2023-24 + 2024-25, then checked once on 2025-26. Each stat's baseline is its current
model, tracking included where it has it.

| Stat | 2023-25 | 2025-26 check |
|---|---|---|
| 3-PT Attempted | 0.2210 → 0.2205, **better** | 0.2209 → 0.2205, **better** |
| Two Pointers Attempted | 0.2339 → 0.2336, **better** | 0.2309 → 0.2305, **better** |
| FG Attempted | 0.2319 → 0.2316, **better** | 0.2311 → 0.2308, **better** |
| Pts+Rebs+Asts | 0.2357 → 0.2354, **better** | 0.2339 → 0.2336, **better** |
| Free Throws Attempted | 0.2365 → 0.2362, **better** | 0.2388 → 0.2385, **better** |
| Free Throws Made | 0.2284 → 0.2280, **better** | no clear difference (−0.0003) |
| Steals | 0.2287 → 0.2285, **better** | no clear difference (−0.0002) |
| Blocked Shots | 0.1986 → 0.1984, **better** | no clear difference (−0.0001) |
| Blks+Stls | 0.2312 → 0.2311, **better** | no clear difference (0.0000) |
| Defensive Rebounds | 0.2356 → 0.2354, **better** | no clear difference (0.0000) |
| 14 others, Fantasy Score, Pts+Rebs, Pts+Asts and Assists among them | no clear difference | |
| Double Doubles | no clear difference | 0.0632 → 0.0634, worse (real) |

Calibration stayed under the 3% limit for every stat on 2025-26 (the largest: Personal Fouls 2.6%).
Saved as `experiments/stat_ab_shots_tune.csv` and `stat_ab_shots_2025.csv`.

**Decision:** the 10 stats that tested better use the shot profile (`features.WITH_SHOTS`); Points and the
other 15 stats keep their inputs. The daily update gets it from the shot-chart download it already did for
dunks, so it costs no extra requests.

**What it shows:** the shot profile helps the shot-volume stats most (attempts, free throws). Where a player
shoots and how he creates his shots says how many shots and trips to the line he gets, beyond his recent
averages. Five stats were better again on the season the decision didn't use; tracking managed that for one.
Like tracking, it doesn't help Points: knowing how a player scores doesn't predict how much.

---

## 5. What would actually move the needle next

1. **Real sportsbook lines.** The line itself is the strongest single input a model can have, and it's the only way to measure a true edge. Log lines daily (the web app records every line you check) and grade them with the Results tab or `score.py`.
2. **Late scratches.** The official injury report and the starting lineups (section 4e) are used, but a scratch after the last report, before the lineup is confirmed, isn't caught.
3. **Vegas spread and game total** (better blowout and pace signals than our team-rating proxies).
4. **Correlation between picks.** Entry odds assume picks are independent; same-game picks aren't.

## 6. Running experiments yourself

```bash
python experiments.py --list                    # all experiments
python experiments.py E2 B1                     # run on the tuning folds (results -> experiments/results.csv)
python experiments.py --compare E2 B1           # is B1 really better?
python tune.py --base B1 --trials 30            # Optuna search
python experiments.py FINAL --holdout           # final exam: only when you're done choosing
python experiments.py E6_tuned E10_lineups --folds 2024   # chosen seasons only (inputs that start in 2023-24)
python stat_models.py --ab lineups              # an input group in every stat model: with vs. without
python learning_curve.py [--mlp]                # watch rounds / epochs
```

To try an idea: add a `reg(Config(...))` line in [experiments.py](experiments.py), run it, and compare it to `FINAL`. Keep it only if the confidence interval says it's real; then make it the new recipe in [nbaline/recipes.py](nbaline/recipes.py), which is what `train.py` uses.

## 7. Retraining faster, with the same models

A full retrain of all 26 models took about 18 minutes. Three changes cut that without changing a single
prediction (`nbaline/modeling.py`, `stat_models.py`):

- **Each model is trained twice:** first on the seasons before the last complete one, to choose the
  round count by early stopping and to calibrate the uncertainty on that season, then on everything.
  That first fit only uses complete past seasons, so it comes out the same all season. It's now saved with
  the model and reused, tagged with a fingerprint of everything it learned from: the settings, every
  input and target value, the library versions, the CPU's thread count and the pipeline code. If any of
  these change (a corrected old box score, a new input, a new season), it's fitted again.
- **A model whose final fit would learn from exactly the same rows is kept as it is** (same fingerprint
  check). An update that finds no new games retrains nothing.
- **Four stat models train side by side**, each in its own process with every CPU thread. Giving each
  fewer threads would be faster still, but XGBoost's trees depend slightly on the thread count, so the
  models would no longer match.

Checked on the November 11 data: all 26 models, the full way and the new way, gave identical
projections, chances of More and push chances (largest difference 0). Times on this computer:

| Retrain | Before | Now |
|---|---|---|
| First one (nothing saved to reuse yet), all 26 models | ~18 min | 10 min |
| After new games (the usual case) | ~18 min | 5.3 min |
| No new games | ~18 min | 0 (an update takes 43 s) |

### On the GPU (November 2026)

XGBoost now builds its trees on the laptop's NVIDIA RTX 3060 whenever it can (`modeling.training_device`).
Predictions still run on the CPU, so the web app never needs the GPU. `NBALINE_DEVICE=cpu` forces the CPU.

**Same models?** Not tree for tree: the GPU draws its random samples of rows and inputs differently. So every
final model was trained both ways on the seasons before 2025-26 and scored on 2025-26, which neither saw
(over/under Brier at the usual line, 95% interval resampling whole nights):

| | Result |
|---|---|
| 25 of 26 models | no clear difference (largest change ±0.0002 Brier) |
| 3-PT Attempted | GPU very slightly better (0.2211 → 0.2209); one such result in 26 tests is expected by chance |
| Points CRPS | 3.4662 → 3.4658, change [−0.0020, +0.0013], no clear difference |
| Calibration | under the 3% limit for every stat both ways (largest: Personal Fouls 2.5% CPU, 2.6% GPU) |

Two GPU fits on the same rows give identical trees, so reusing the first fit (above) still works. The
fingerprint includes GPU or CPU, so switching between them retrains everything once.

**Times on this laptop:**

| | CPU | GPU |
|---|---|---|
| One model's trees: Points (1,199 trees) / Rebounds (1,000 trees) | 10.6 s / 11.8 s | 4.1 s / 3.7 s |
| All 26 models from scratch | ~10 min | 5.8 min (Points 1.7, other stats 4.1) |

The whole retrain isn't 3× faster: the Points neural net (scikit-learn) and building the inputs stay on
the CPU, and the four stat models training side by side share one GPU.
