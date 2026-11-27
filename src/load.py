import os
import sqlite3
import tempfile
from pathlib import Path

from src.validate import DATA_DIR, ValidationError, validate_sources


DATABASE = DATA_DIR / "cs.db"
SCHEMA = Path(__file__).with_name("schema.sql")


def _insert_data(connection, data):
    connection.executemany(
        "INSERT INTO teams (team_id, canonical_name) VALUES (?, ?)",
        data["entities"]["team"].items(),
    )
    connection.executemany(
        "INSERT INTO players (player_id, canonical_name) VALUES (?, ?)",
        data["entities"]["player"].items(),
    )
    for table, id_column, kind in (
        ("team_aliases", "team_id", "team"),
        ("player_aliases", "player_id", "player"),
    ):
        connection.executemany(
            f"INSERT INTO {table} (alias_key, alias, {id_column}, source_url) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    row["alias_key"],
                    row["alias"],
                    row["entity_id"],
                    row["source_url"],
                )
                for row in data["aliases"][kind]
            ],
        )

    connection.executemany(
        "INSERT INTO events "
        "(event_id, name, tier, is_lan, format, start_date, end_date, is_major, source_url) "
        "VALUES (:event_id, :name, :tier, :is_lan, :format, :start_date, :end_date, "
        ":is_major, :source_url)",
        data["events"],
    )
    connection.executemany(
        "INSERT INTO matches "
        "(match_id, event_id, date, round_name, team_a_id, team_b_id, score_a, "
        "score_b, best_of, source_url) "
        "VALUES (:match_id, :event_id, :date, :round_name, :team_a_id, :team_b_id, "
        ":score_a, :score_b, :best_of, :source_url)",
        data["matches"],
    )
    connection.executemany(
        "INSERT INTO maps (map_id, name) VALUES (:map_id, :name)",
        data["maps"],
    )
    connection.executemany(
        "INSERT INTO map_results "
        "(match_id, map_number, map_id, score_a, score_b) "
        "VALUES (:match_id, :map_number, :map_id, :score_a, :score_b)",
        data["map_results"],
    )
    connection.executemany(
        "INSERT INTO player_series_ratings (match_id, player_id, rating) "
        "VALUES (:match_id, :player_id, :rating)",
        data["player_series_ratings"],
    )
    connection.executemany(
        "INSERT INTO player_map_ratings "
        "(match_id, map_number, player_id, rating) "
        "VALUES (:match_id, :map_number, :player_id, :rating)",
        data["player_map_ratings"],
    )
    connection.executemany(
        "INSERT INTO veto_actions "
        "(match_id, action_number, action, map_id, team_id) "
        "VALUES (:match_id, :action_number, :action, :map_id, :team_id)",
        data["veto_actions"],
    )
    connection.executemany(
        "INSERT INTO roster_stints "
        "(team_id, player_id, start_date, end_date, is_stand_in, known_at, source_url) "
        "VALUES (:team_id, :player_id, :start_date, :end_date, :is_stand_in, "
        ":known_at, :source_url)",
        data["roster_stints"],
    )


def rebuild_database(data_dir=DATA_DIR, database=DATABASE):
    data = validate_sources(data_dir)
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{database.name}.", suffix=".tmp", dir=database.parent
    )
    os.close(descriptor)
    temporary_database = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary_database)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(SCHEMA.read_text(encoding="utf-8"))
            _insert_data(connection, data)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"foreign key check failed: {violations[0]}"
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(f"database integrity check failed: {integrity}")
            connection.commit()
        finally:
            connection.close()
        os.replace(temporary_database, database)
    finally:
        if temporary_database.exists():
            temporary_database.unlink()

    return data


def main():
    try:
        data = rebuild_database()
    except (OSError, sqlite3.Error, ValidationError) as exc:
        raise SystemExit(f"load failed: {exc}") from exc

    print(
        f"Rebuilt {DATABASE} from raw sources: "
        f"{len(data['entities']['team'])} teams, "
        f"{len(data['entities']['player'])} players, "
        f"{len(data['events'])} events, {len(data['matches'])} matches, "
        f"{len(data['map_results'])} map results, "
        f"{len(data['player_series_ratings'])} series ratings, "
        f"{len(data['player_map_ratings'])} map ratings, "
        f"{len(data['roster_stints'])} roster stints."
    )


if __name__ == "__main__":
    main()
