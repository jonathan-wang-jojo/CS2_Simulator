import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from src.elo import backtest, brier_score


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "cs.db"

MATCH_QUERY = """
SELECT
    matches.match_id,
    matches.date,
    matches.team_a_id,
    matches.team_b_id,
    matches.score_a,
    matches.score_b,
    events.is_lan
FROM matches
JOIN events USING (event_id)
ORDER BY matches.date, matches.match_id
"""


def run(database=DATABASE):
    database = Path(database)
    if not database.is_file():
        raise FileNotFoundError(
            f"{database} does not exist; run `python -m src.load` first"
        )
    with closing(sqlite3.connect(database)) as connection:
        matches = pd.read_sql_query(
            MATCH_QUERY, connection, parse_dates=["date"]
        )
    return backtest(matches)


def main():
    try:
        ratings, predictions = run()
    except (OSError, sqlite3.Error) as exc:
        raise SystemExit(f"backtest failed: {exc}") from exc

    if predictions.empty:
        print("No matches in data/cs.db. Add sourced event data and rebuild.")
        return

    print(f"Period: {predictions.date.min().date()} to {predictions.date.max().date()}")
    print(f"Point-in-time Brier score: {brier_score(predictions):.3f}")
    print(f"Predictions: {len(predictions)}")
    print(f"Rated teams: {len(ratings)}")


if __name__ == "__main__":
    main()
