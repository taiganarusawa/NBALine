"""The model's chance during a game: the pre-game projection, updated with what he's done so far.

Before tip-off the model gives each line a projection (mu) and a spread (sd) for the whole game. During
the game three more things are known: his number so far, his minutes and how much of the game is left.
The rest of his game is then modeled the way count stats behave (a Poisson-gamma mix, the same family as
the count models' negative binomial):

  * His rate tonight. Before tip-off it's mu over his usual minutes, give or take what the model's sd
    says about how much a player's rate moves from game to game. What he's done so far updates it (Bayes):
    a hot start raises it, by more the longer he's played, but not all the way to his current pace.
  * His minutes left: the game minutes left times his share of the floor (his usual share, updated
    with tonight's: foul trouble or a blowout shows up here).
  * The rest of his game: that rate times those minutes, plus the game's own randomness. Some stats come
    in lumps (a 3-pointer is 3 points at once), which makes a game noisier than counting one by one.
    EVENT_SIZE is how lumpy each stat is: its variance-to-mean ratio within a game, from league
    per-game averages (points: 2 and 3-point makes and free throws give about 2.2).

His minutes left are uncertain too (fouls, blowouts, overtime): MINUTES_LEFT_SPREAD.

Tested on Nov 10, 2026 (932 graded lines, the box scores rebuilt at the end of Q1, halftime and the end of
Q3 from stats.nba.com): the live chance's Brier score beat both the pre-game chance and "he keeps his
pace" at every checkpoint. Without the minutes spread it was overconfident (its 95% lines hit 87%); 0.5
gave the best halftime score, and larger values only helped late in games. One night, and the pre-game
model ran about 5 points high on More that night, which the live chance carries over.
"""
from scipy.stats import gamma

GAME_MINUTES = 48
EVENT_SIZE = {"Points": 2.2, "Pts+Rebs+Asts": 1.74, "Pts+Rebs": 1.86, "Pts+Asts": 1.98, "Fantasy Score": 2.2,
              "Free Throws Made": 1.8, "Free Throws Attempted": 1.8}   # every other stat counts one by one
USUAL_SHARE_WEIGHT = 24       # his usual share of the floor counts like this many game minutes of tonight's
MINUTES_LEFT_SPREAD = 0.5     # his minutes left are uncertain (fouls, blowouts, overtime): their sd, as a share
WHOLE_NUMBER_EXCEPT = {"Fantasy Score"}
YES_NO = {"Double Doubles", "Triple Doubles"}   # he gets one or he doesn't: no rate to update


def live_chance(stat: str, line: float, proj: float | None, sd: float | None, usual_minutes: float | None,
                value: float, minutes: float, share_played: float | None) -> dict | None:
    """{"more": chance, "less": chance, "push": chance, "expected": his likely final number} while the
    game is on. More + Less = 100%, like before tip-off: on a whole-number line the chance he finishes
    exactly on it (a push: the pick reverts) is set aside, and given on its own as "push".
    None when there's nothing to start from (no projection, a yes/no stat, the game not under way)."""
    if (stat in YES_NO or proj is None or not sd or not usual_minutes
            or share_played is None or not 0 <= share_played < 1):
        return None
    lump = EVENT_SIZE.get(stat, 1.0)
    mu = max(proj, 0.05)
    usual = min(max(usual_minutes, 1.0), GAME_MINUTES)

    # his rate per minute, counted in lumps; the prior's strength (shape) comes from the model's spread,
    # after taking out the randomness any single game has anyway
    between_games = max(sd ** 2 - lump * mu, 0.02 * mu ** 2)
    shape = min(mu ** 2 / between_games, 100.0)
    rate = (shape + max(value, 0) / lump) / (shape * lump * usual / mu + minutes)
    shape += max(value, 0) / lump

    # his minutes left: the game's minutes left times his share of the floor
    elapsed = GAME_MINUTES * share_played
    share = (usual / GAME_MINUTES * USUAL_SHARE_WEIGHT + minutes) / (USUAL_SHARE_WEIGHT + elapsed)
    minutes_left = min(share, 1.0) * GAME_MINUTES * (1 - share_played)

    # the rest of his game, as a gamma curve with the Poisson-gamma mix's mean and variance
    mean = lump * rate * minutes_left
    var = lump * mean + mean ** 2 / shape + (MINUTES_LEFT_SPREAD * mean) ** 2
    whole = stat not in WHOLE_NUMBER_EXCEPT
    half = 0.5 if whole and line == round(line) else 0.0   # whole-number stat on a whole line: k covers k-0.5 .. k+0.5
    need = line - value
    more = _above(need + half, mean, var) if whole else _above(need, mean, var)
    less = 1 - _above(need - half, mean, var)
    return dict(more=more / max(more + less, 1e-9), less=less / max(more + less, 1e-9),
                push=min(max(1 - more - less, 0.0), 1.0), expected=round(value + mean, 1))


def _above(threshold: float, mean: float, var: float) -> float:
    """Chance the rest of his game adds more than `threshold`."""
    if threshold < 0:
        return 1.0
    if mean <= 1e-9:
        return 0.0
    return float(gamma.sf(threshold, a=mean ** 2 / var, scale=var / mean))
