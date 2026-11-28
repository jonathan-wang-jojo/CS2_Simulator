import csv
import json
import sqlite3
import tempfile
import unittest
import warnings
from contextlib import closing
from pathlib import Path

from src.import_event import import_event
from src.import_event_tsv import import_event_from_tsv
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
            ("team", "team:alpha", "Team Alpha", "Team Alphaa"),
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
                (*row, f"https://www.hltv.org/team/{row[1]}") for row in rows
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
                    "https://www.hltv.org/team/alpha",
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
                "source_url": "https://www.hltv.org/events/test",
                "provenance": {
                    "retrieved_on": "2026-01-04",
                    "verified_by": "test reviewer",
                },
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
                    "source_url": "https://www.hltv.org/matches/001",
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
                    "source_url": "https://www.hltv.org/matches/002",
                },
                {
                    "match_id": "match:test-event-003",
                    "date": "2026-01-02",
                    "team_a": "Alpha",
                    "team_b": "Team Charlie",
                    "score_a": 2,
                    "score_b": 0,
                    "best_of": 3,
                    "source_url": "https://www.hltv.org/matches/003",
                },
            ],
        }

    def _write_event(self, document=None):
        document = document or self._event_document()
        event = document["event"]
        event_slug = event["event_id"].split(":", 1)[1]
        path = self.raw_dir / event["start_date"][:4] / f"{event_slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, indent=2),
            encoding="utf-8",
        )
        return path

    def _add_cross_checks(self, document, mismatched_match_id=None):
        source_dir = self.data_dir / "source" / "test-event"
        source_dir.mkdir(parents=True)
        primary_capture = source_dir / "primary.txt"
        secondary_capture = source_dir / "secondary.txt"
        primary_capture.write_text("primary capture\n", encoding="utf-8")
        secondary_capture.write_text("secondary capture\n", encoding="utf-8")
        document["event"]["provenance"] = {
            "retrieved_on": "2026-01-04",
            "verified_by": "test reviewer",
            "source_capture_files": [
                "source/test-event/primary.txt",
                "source/test-event/secondary.txt",
            ],
        }
        for match in document["matches"]:
            checked_score_a = match["score_a"]
            checked_score_b = match["score_b"]
            if match["match_id"] == mismatched_match_id:
                checked_score_a, checked_score_b = checked_score_b, checked_score_a
            match["cross_check"] = {
                "date": match["date"],
                "team_a": match["team_a"],
                "team_b": match["team_b"],
                "score_a": checked_score_a,
                "score_b": checked_score_b,
                "best_of": match["best_of"],
                "source_url": (
                    "https://liquipedia.net/counterstrike/matches/"
                    + match["match_id"].rsplit("-", 1)[-1]
                ),
                "retrieved_on": "2026-01-04",
                "verified_by": "test reviewer",
                "source_capture_file": "source/test-event/secondary.txt",
            }
        return primary_capture, secondary_capture

    def test_rebuild_creates_normalized_database_and_is_repeatable(self):
        raw_event = self.raw_dir / "2026" / "test-event.json"
        original_event = raw_event.read_bytes()

        data = rebuild_database(self.data_dir, self.database)
        first_database = self.database.read_bytes()
        rebuild_database(self.data_dir, self.database)

        self.assertEqual(len(data["matches"]), 3)
        self.assertEqual(self.database.read_bytes(), first_database)
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

    def test_validate_discovers_events_in_year_folders(self):
        data = validate_sources(self.data_dir)

        self.assertEqual(
            [event["event_id"] for event in data["events"]],
            ["event:test-event"],
        )

    def test_player_ratings_load_at_series_and_map_scope(self):
        document = self._event_document()
        document["matches"][0]["player_ratings"] = [
            {"player": "Player One", "rating": 1.25}
        ]
        document["matches"][0]["maps"][0]["player_ratings"] = [
            {"player": "Player One", "rating": 1.31}
        ]
        self._write_event(document)

        data = rebuild_database(self.data_dir, self.database)

        self.assertEqual(
            data["player_series_ratings"],
            [
                {
                    "match_id": "match:test-event-001",
                    "player_id": "player:one",
                    "rating": 1.25,
                }
            ],
        )
        self.assertEqual(
            data["player_map_ratings"],
            [
                {
                    "match_id": "match:test-event-001",
                    "map_number": 1,
                    "player_id": "player:one",
                    "rating": 1.31,
                }
            ],
        )
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT rating FROM player_series_ratings"
                ).fetchone()[0],
                1.25,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT rating FROM player_map_ratings"
                ).fetchone()[0],
                1.31,
            )

    def test_player_ratings_require_registered_names(self):
        document = self._event_document()
        document["matches"][0]["player_ratings"] = [
            {"player": "Unknown Player", "rating": 1.25}
        ]
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "unknown player name"):
            validate_sources(self.data_dir)

    def test_player_ratings_reject_duplicate_players_at_same_scope(self):
        document = self._event_document()
        document["matches"][0]["player_ratings"] = [
            {"player": "Player One", "rating": 1.25},
            {"player": "Player One", "rating": 1.18},
        ]
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "duplicate player"):
            validate_sources(self.data_dir)

    def test_player_ratings_reject_non_finite_values(self):
        document = self._event_document()
        document["matches"][0]["player_ratings"] = [
            {"player": "Player One", "rating": float("nan")}
        ]
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "finite number"):
            validate_sources(self.data_dir)

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

    def test_rejects_duplicate_matchup_with_reversed_order_and_different_round(self):
        document = self._event_document()
        duplicate = dict(document["matches"][0])
        duplicate.update(
            {
                "match_id": "match:test-event-004",
                "team_a": "Team Bravo",
                "team_b": "Alpha",
                "round": "A later round",
                "source_url": "https://www.hltv.org/matches/004",
            }
        )
        document["matches"].append(duplicate)
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "duplicate event/date"):
            validate_sources(self.data_dir)

    def test_alias_matching_accepts_case_spacing_and_registered_spelling_variants(self):
        document = self._event_document()
        document["matches"][0]["team_a"] = "  tEaM   aLpHaa  "
        self._write_event(document)

        data = validate_sources(self.data_dir)

        self.assertEqual(data["matches"][0]["team_a_id"], "team:alpha")

    def test_event_roster_and_expected_series_count_are_checked(self):
        document = self._event_document()
        document["event"]["teams"] = ["Alpha", "Team Bravo", "Team Charlie"]
        document["event"]["expected_match_count"] = 3
        self._write_event(document)
        self.assertEqual(len(validate_sources(self.data_dir)["matches"]), 3)

        document["event"]["teams"] = ["Alpha", "Team Bravo"]
        self._write_event(document)
        with self.assertRaisesRegex(ValidationError, "not listed in event teams"):
            validate_sources(self.data_dir)

    def test_cross_source_mismatch_is_reported_and_stops_validation(self):
        document = self._event_document()
        primary, secondary = self._add_cross_checks(
            document, mismatched_match_id="match:test-event-001"
        )
        original_primary = primary.read_bytes()
        original_secondary = secondary.read_bytes()
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "human resolution is required"):
            validate_sources(self.data_dir)

        report = self.data_dir / "reports" / "discrepancies.json"
        discrepancies = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(
            any(
                row["match_id"] == "match:test-event-001"
                and row["field"].startswith("score:")
                for row in discrepancies
            )
        )
        self.assertEqual(primary.read_bytes(), original_primary)
        self.assertEqual(secondary.read_bytes(), original_secondary)

    def test_cross_check_coverage_is_recorded(self):
        document = self._event_document()
        self._add_cross_checks(document)
        self._write_event(document)

        data = validate_sources(self.data_dir)

        self.assertEqual(data["coverage"][0]["cross_checked_count"], 3)
        self.assertEqual(data["coverage"][0]["discrepancies_found"], 0)
        self.assertTrue(data["coverage"][0]["provenance_recorded"])

    def test_manual_hltv_provenance_needs_no_capture_or_backup_check(self):
        self._write_event()

        data = validate_sources(self.data_dir)

        self.assertEqual(data["coverage"][0]["cross_checked_count"], 0)
        self.assertEqual(data["coverage"][0]["provenance"]["source_capture_files"], [])

    def test_accepts_non_hltv_https_primary_source(self):
        document = self._event_document()
        document["matches"][0]["source_url"] = "https://example.test/match/001"
        self._write_event(document)

        data = validate_sources(self.data_dir)
        self.assertEqual(
            data["matches"][0]["source_url"],
            "https://example.test/match/001",
        )

    def test_import_event_validates_and_copies_local_json(self):
        document = self._event_document()
        document["event"]["event_id"] = "event:second-event"
        document["event"]["source_url"] = "https://www.hltv.org/events/second"
        document["event"]["start_date"] = "2025-01-01"
        document["event"]["end_date"] = "2025-01-03"
        for index, match in enumerate(document["matches"], start=1):
            match["match_id"] = f"match:second-event-{index:03d}"
            match["date"] = f"2025-01-0{index}"
            match["source_url"] = (
                f"https://www.hltv.org/matches/second-{index:03d}"
            )
        export_path = self.data_dir.parent / "second-event-export.json"
        export_path.write_text(json.dumps(document), encoding="utf-8")
        original_export = export_path.read_bytes()

        destination = import_event(export_path, self.data_dir)

        self.assertEqual(
            destination,
            self.raw_dir / "2025" / "second-event.json",
        )
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), document)
        self.assertEqual(export_path.read_bytes(), original_export)
        self.assertEqual(len(validate_sources(self.data_dir)["events"]), 2)
        coverage = json.loads(
            (self.data_dir / "reports" / "coverage.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(coverage), 2)

    def test_import_event_tsv_generates_match_ids_and_imports_rows(self):
        event = self._event_document()["event"]
        event["event_id"] = "event:tsv-event"
        event["source_url"] = "https://www.hltv.org/events/tsv-event"
        event["teams"] = ["Team Alpha", "Team Bravo", "Team Charlie"]
        event["expected_match_count"] = 2
        metadata_path = self.data_dir.parent / "tsv-event.json"
        metadata_path.write_text(json.dumps(event), encoding="utf-8")

        matches_path = self.data_dir.parent / "tsv-matches.tsv"
        with matches_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(
                output,
                delimiter="\t",
                fieldnames=[
                    "date",
                    "team_a",
                    "team_b",
                    "score_a",
                    "score_b",
                    "best_of",
                    "source_url",
                    "round",
                ],
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "date": "2026-01-01",
                        "team_a": "Alpha",
                        "team_b": "Team Bravo",
                        "score_a": 2,
                        "score_b": 0,
                        "best_of": 3,
                        "source_url": "https://www.hltv.org/matches/tsv-001",
                        "round": "Swiss round 1",
                    },
                    {
                        "date": "2026-01-02",
                        "team_a": "Team Alpha",
                        "team_b": "Team Charlie",
                        "score_a": 2,
                        "score_b": 1,
                        "best_of": 3,
                        "source_url": "https://www.hltv.org/matches/tsv-002",
                    },
                ]
            )

        destination = import_event_from_tsv(
            metadata_path,
            matches_path,
            self.data_dir,
        )

        imported = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(
            [match["match_id"] for match in imported["matches"]],
            ["match:tsv-event-001", "match:tsv-event-002"],
        )
        self.assertEqual(imported["matches"][0]["round"], "Swiss round 1")
        self.assertEqual(imported["matches"][1]["score_b"], 1)
        self.assertEqual(len(validate_sources(self.data_dir)["events"]), 2)

        original_content = destination.read_bytes()
        with self.assertRaisesRegex(FileExistsError, "destination already exists"):
            import_event_from_tsv(metadata_path, matches_path, self.data_dir)
        self.assertEqual(destination.read_bytes(), original_content)

    def test_import_event_tsv_rejects_bad_integer_without_importing(self):
        event = self._event_document()["event"]
        event["event_id"] = "event:invalid-tsv-event"
        metadata_path = self.data_dir.parent / "invalid-tsv-event.json"
        metadata_path.write_text(json.dumps(event), encoding="utf-8")

        matches_path = self.data_dir.parent / "invalid-tsv-matches.tsv"
        matches_path.write_text(
            "date\tteam_a\tteam_b\tscore_a\tscore_b\tbest_of\tsource_url\n"
            "2026-01-01\tAlpha\tTeam Bravo\twin\t0\t3\t"
            "https://www.hltv.org/matches/invalid-tsv\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValidationError, "score_a must be an integer"):
            import_event_from_tsv(metadata_path, matches_path, self.data_dir)

        self.assertFalse(
            (self.raw_dir / "2026" / "invalid-tsv-event.json").exists()
        )

    def test_import_event_rejects_invalid_export_without_copying(self):
        document = self._event_document()
        document["event"]["event_id"] = "event:second-event"
        for index, match in enumerate(document["matches"], start=1):
            match["match_id"] = f"match:second-event-{index:03d}"
            match["source_url"] = (
                f"https://www.hltv.org/matches/second-{index:03d}"
            )
        document["matches"][0]["score_a"] = 0
        export_path = self.data_dir.parent / "invalid-event-export.json"
        export_path.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(ValidationError, "plausible result"):
            import_event(export_path, self.data_dir)

        self.assertFalse(
            (self.raw_dir / "2026" / "second-event.json").exists()
        )
        self.assertEqual(len(validate_sources(self.data_dir)["events"]), 1)

    def test_import_event_refuses_to_overwrite(self):
        source_path = self._write_event()
        original = source_path.read_bytes()

        with self.assertRaisesRegex(FileExistsError, "destination already exists"):
            import_event(source_path, self.data_dir)

        self.assertEqual(source_path.read_bytes(), original)

    def test_rejects_non_https_primary_source(self):
        document = self._event_document()
        document["matches"][0]["source_url"] = "http://example.test/match/001"
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "HTTPS source URL"):
            validate_sources(self.data_dir)

    def test_requires_event_provenance(self):
        document = self._event_document()
        del document["event"]["provenance"]
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "event provenance is required"):
            validate_sources(self.data_dir)

    def test_rejects_non_liquipedia_backup(self):
        document = self._event_document()
        self._add_cross_checks(document)
        document["matches"][0]["cross_check"]["source_url"] = (
            "https://example.test/matches/001"
        )
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "Liquipedia backup URL"):
            validate_sources(self.data_dir)

    def test_rejects_windows_separator_capture_traversal(self):
        document = self._event_document()
        self._add_cross_checks(document)
        document["matches"][0]["cross_check"]["source_capture_file"] = (
            "source\\test-event\\..\\..\\outside.txt"
        )
        self._write_event(document)

        with self.assertRaisesRegex(ValidationError, "relative path under"):
            validate_sources(self.data_dir)

    def test_human_resolution_is_recorded_and_allows_validation(self):
        document = self._event_document()
        self._add_cross_checks(document, mismatched_match_id="match:test-event-001")
        document["event"]["discrepancy_resolutions"] = [
            {
                "match_id": "match:test-event-001",
                "resolved_on": "2026-01-05",
                "resolved_by": "test reviewer",
                "resolution": "Primary source confirmed after manual review.",
            }
        ]
        self._write_event(document)

        data = validate_sources(self.data_dir)
        report = json.loads(
            (self.data_dir / "reports" / "discrepancies.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertGreater(data["coverage"][0]["discrepancies_found"], 0)
        self.assertEqual(
            data["coverage"][0]["discrepancies_resolved"],
            data["coverage"][0]["discrepancies_found"],
        )
        self.assertTrue(all(row["resolved"] for row in report))

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
