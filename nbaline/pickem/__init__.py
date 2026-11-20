"""Everything PrizePicks-specific.

    payouts.py   payout tables, entry odds and break-even per pick
    board.py     reads a pasted PrizePicks board into {player, stat, line} rows
    ranking.py   ranks a board's lines by the model's chance of hitting
    lineup.py    builds the lineups to play from a ranked board (standard, Goblins, Demons)
    store.py     saves checked lines, boards and entries (SQLite) and grades them after the games
"""
