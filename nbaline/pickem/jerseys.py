"""Players' jersey numbers, shown next to their names on My entries.

Source: NBA.com's player index (cdn.nba.com, the file NBA.com's Players page reads; free, no login):
everyone on a roster this season with his current team and number, in one small file (~280 KB). It's
read again after REFRESH_SECONDS, so a trade or a new number shows up the same day. Until it has been
read (or while NBA.com doesn't answer), names simply show without a number.
"""
import sys
import time

import requests

from .live import FEED_HEADERS

URL = "https://cdn.nba.com/static/json/staticData/playerIndex.json"
TIMEOUT = 8                     # seconds to wait for the file
REFRESH_SECONDS = 6 * 3600      # read again after this long
RETRY_SECONDS = 5 * 60          # after a failed read, try again after this long (the last numbers stay)

_numbers: dict[int, str] = {}   # player_id -> "34"
_next_read = 0.0                # time.time() after which the file is read again


def numbers() -> dict[int, str]:
    """{player_id: jersey number as NBA.com writes it ("0", "00", "34")}. Players without a number are
    left out."""
    global _numbers, _next_read
    if time.time() < _next_read:
        return _numbers
    try:
        r = requests.get(URL, headers=FEED_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        table = r.json()["resultSets"][0]
        col = {name: i for i, name in enumerate(table["headers"])}
        _numbers = {int(row[col["PERSON_ID"]]): str(row[col["JERSEY_NUMBER"]]) for row in table["rowSet"]
                    if row[col["JERSEY_NUMBER"]] not in (None, "")}
        _next_read = time.time() + REFRESH_SECONDS
    except Exception as e:   # names show without numbers until it answers
        print(f"[jerseys] couldn't read NBA.com's player index: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _next_read = time.time() + RETRY_SECONDS
    return _numbers


def add_to(picks: list[dict]) -> None:
    """Adds each pick's jersey number ("jersey", None if unknown), by its player_id."""
    known = numbers()
    for p in picks:
        p["jersey"] = known.get(p.get("player_id"))
