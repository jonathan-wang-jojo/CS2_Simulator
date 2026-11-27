import csv
import json
import sqlite3
import tempfile
import unittest
import warnings
from contextlib import closing
from pathlib import Path

from src.load import rebuild_database
from src.validate import ValidationError, validate_sources


class DataPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name) / "data"
        self.raw_dir = self.data_dir / "raw"
        self.raw_dir.mkdir(parents=True)
        self.database = self.data_dir / "cs.db"
        self._write_registry()
        self._write_rosters()
        self._write_event()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_registry(self):
        rows = [
            ("team", "team:alpha", "Team Alpha", "Team Alpha"),
            ("team", "team:alpha", "Team Alpha", "Alpha"),
            ("team", "team:bravo", "Team Bravo", "Team Bravo"),
            ("team", "team:charlie", "Team Charlie", "Team Charlie"),
            ("player", "player:one", "Player One", "Player One"),
        ]
        with (self.data_dir / "entities.csv").open(
            "w", newline="", encoding="utf-8"
        ) as output:
            writer = csv.writer(output)
            writer.writerow(
                ["entity_type", "entity_id", "canonical_name", "alias", "source_url"]
            )
            writer.writerows(
                (*row, f"https://example.test/{row[1]}") for row in rows
            )

    def _write_rosters(self):
        with (self.raw_dir / "roster_stints.csv").open(
            "w", newline="", encoding="utf-8"
        ) as output:
            writer = csv.writer(output)
            writer.writerow(
                [
                    "team",
                    "player",
                    "start_date",
                    "end_date",
                    "is_stand_in",
                    "known_at",
                    "source_url",
                ]
            )
            writer.writerow(
                [
                    "Alpha",
                    "Player One",
                    "2026-01-01",
                    "",
                    "false",
                    "2025-12-31",
                    "https://example.test/roster/alpha",
                ]
            )

    def _event_document(self):
        return {
            "event": {
                "event_id": "event:test-event",
                "name": "Test Event",
                "tier": "S",
                "is_lan": True,
                "format": "Swiss",
                "start_date": "2026-01-01",
                "end_date": "2026-01-03",
                "is_major": False,
                "source_url": "https://example.test/events/test",
            },
            "matches": [
                {
                    "match_id": "match:test-event-001",
                    "date": "2026-01-01",
                    "team_a": "Alpha",
                    "team_b": "Team Bravo",
                    "score_a": 2,
                    "score_b": 0,
                    "best_of": 3,
                    "source_url": "https://example.test/matches/001",
                    "maps": [
                        {"map_name": "Nuke", "score_a": 13, "score_b": 8},
                        {"map_name": "Mirage", "score_a": 13, "score_b": 10},
                    ],
                    "veto_actions": [
                        {
                            "action": "pick",
                            "team": "Alpha",
                            "map_name": "Nuke",
                        },
                        {
                            "action": "ban",
                            "team": "Team Bravo",
                            "map_name": "Ancient",
                        },
                    ],
                },
                {
                    "match_id": "match:test-event-002",
                    "date": "2026-01-01",
                    "team_a": "Team Alpha",
                    "team_b": "Team Charlie",
                    "score_a": 2,
                    "score_b": 0,
                    "best_of": 3,
                    "source_url": "https://example.test/matches/002",
                },
                {
                    "match_id": "match:test-event-003",
                    "date": "2026-01-02",
                    "team_a": "Alpha",
                    "team_b": "Team Charlie",
                    "score_a": 2,
                    "score_b": 0,
                    "best_of": 3,
                    "source_url": "https://example.test/matches/003",
                },
            ],
        }

    def _write_event(self, document=None):
        path = self.raw_dir / "test-event.json"
        path.write_text(
            json.dumps(document or self._event_document(), indent=2),
            encoding="utf-8",
        )
        return path

    def test_rebuild_creates_normalized_database_and_is_repeatable(self):
        raw_event = self.raw_dir / "test-event.json"
        original_event = raw_event.read_bytes()

        data = rebuild_database(self.data_dir, self.database)
        rebuild_database(self.data_dir, self.database)

        self.assertEqual(len(data["matches"]), 3)
        self.assertEqual(raw_event.read_bytes(), original_event)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM map_results").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM maps").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM veto_actions").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM roster_stints").fetchone()[0], 1)
            self.assertEqual(
                connection.execute(
                    "SELECT team_a_id FROM matches WHERE match_id = 'match:test-event-001'"
                ).fetchone()[0],
                "team:alpha",
            )
            self.assertEqual(
                connection.execute(
                    "SELECT known_at FROM roster_stints"
                ).fetchone()[0],
                "2025-12-31",
            )

    def test_unknown_alias_fails_and_preserves_existing_database(self):
        rebuild_database(self.data_dir, self.database)
        original_database = self.database.read_bytes()
        document = self._event_document()
        document["matches"][0]["team_a"] = "Unregistered Name"
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "unknown team name"):
            rebuild_database(self.data_dir, self.database)

        self.assertEqual(self.database.read_bytes(), original_database)

    def test_rejects_self_match_and_date_outside_event(self):
        document = self._event_document()
        document["matches"][0]["team_b"] = "Alpha"
        self._write_event(document)
        with self.assertRaisesRegex(ValidationError, "cannot play itself"):
            validate_sources(self.data_dir)

        document = self._event_document()
        document["matches"][0]["date"] = "2025-12-31"
        self._write_event(document)
        with self.assertRaisesRegex(ValidationError, "outside the event date range"):
            validate_sources(self.data_dir)

    def test_rejects_duplicate_matchup_with_reversed_team_order(self):
        document = self._event_document()
        duplicate = dict(document["matches"][0])
        duplicate.update(
            {
                "match_id": "match:test-event-004",
                "team_a": "Team Bravo",
                "team_b": "Alpha",
                "source_url": "https://example.test/matches/004",
            }
        )
        document["matches"].append(duplicate)
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "duplicate event/date"):
            validate_sources(self.data_dir)

    def test_roster_unknown_player_must_be_registered(self):
        roster_path = self.raw_dir / "roster_stints.csv"
        with roster_path.open(encoding="utf-8") as source:
            rows = list(csv.reader(source))
        rows[1][1] = "Unknown Player"
        with roster_path.open("w", newline="", encoding="utf-8") as output:
            csv.writer(output).writerows(rows)

        with self.assertRaisesRegex(ValidationError, "unknown player name"):
            validate_sources(self.data_dir)

    def test_rejects_map_results_that_disagree_with_series_score(self):
        document = self._event_document()
        document["matches"][0]["maps"][0]["score_a"] = 2
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "map results do not agree"):
            validate_sources(self.data_dir)

    def test_unknown_blocks_warn_and_raw_remains_unchanged(self):
        document = self._event_document()
        document["player_stats"] = [{"player": "Player One"}]
        path = self._write_event(document)
        original = path.read_bytes()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            validate_sources(self.data_dir)

        self.assertTrue(any("player_stats" in str(warning.message) for warning in caught))
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
