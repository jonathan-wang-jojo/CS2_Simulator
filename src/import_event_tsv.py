import argparse
import csv
import json
import tempfile
from pathlib import Path

from src.import_event import import_event
from src.validate import DATA_DIR, ID_PATTERN, ValidationError


REQUIRED_COLUMNS = {
    "date",
    "team_a",
    "team_b",
    "score_a",
    "score_b",
    "best_of",
    "source_url",
}
OPTIONAL_COLUMNS = {"round"}


def _read_event_metadata(path):
    try:
        event = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path}: cannot read event metadata: {exc}") from exc

    if not isinstance(event, dict):
        raise ValidationError(f"{path}: event metadata must be a JSON object")

    event_id = event.get("event_id")
    if (
        not isinstance(event_id, str)
        or not ID_PATTERN.fullmatch(event_id)
        or not event_id.startswith("event:")
    ):
        raise ValidationError(f"{path}: event_id must be a valid event ID")

    return event, event_id.split(":", 1)[1]


def _read_match_rows(path, event_slug):
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, delimiter="\t")
            columns = reader.fieldnames or []
            if len(columns) != len(set(columns)):
                raise ValidationError(f"{path}: duplicate TSV column names")

            missing = REQUIRED_COLUMNS - set(columns)
            unknown = set(columns) - REQUIRED_COLUMNS - OPTIONAL_COLUMNS
            if missing or unknown:
                details = []
                if missing:
                    details.append(f"missing columns: {', '.join(sorted(missing))}")
                if unknown:
                    details.append(f"unknown columns: {', '.join(sorted(unknown))}")
                raise ValidationError(f"{path}: {'; '.join(details)}")

            matches = []
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValidationError(
                        f"{path}: row {row_number} has more cells than the header"
                    )
                if all(value is None or not value.strip() for value in row.values()):
                    continue

                values = {
                    key: value.strip() if value is not None else ""
                    for key, value in row.items()
                }
                for column in REQUIRED_COLUMNS:
                    if not values[column]:
                        raise ValidationError(
                            f"{path}: row {row_number} has an empty {column}"
                        )

                scores = {}
                for column in ("score_a", "score_b", "best_of"):
                    try:
                        scores[column] = int(values[column])
                    except ValueError as exc:
                        raise ValidationError(
                            f"{path}: row {row_number} {column} must be an integer"
                        ) from exc

                match = {
                    "match_id": f"match:{event_slug}-{len(matches) + 1:03d}",
                    "date": values["date"],
                    "team_a": values["team_a"],
                    "team_b": values["team_b"],
                    "score_a": scores["score_a"],
                    "score_b": scores["score_b"],
                    "best_of": scores["best_of"],
                    "source_url": values["source_url"],
                }
                if values.get("round"):
                    match["round"] = values["round"]
                matches.append(match)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValidationError(f"{path}: cannot read match TSV: {exc}") from exc

    if not matches:
        raise ValidationError(f"{path}: no match rows found")
    return matches


def import_event_from_tsv(event_metadata_path, matches_path, data_dir=DATA_DIR):
    event, event_slug = _read_event_metadata(Path(event_metadata_path))
    matches = _read_match_rows(Path(matches_path), event_slug)
    document = {"event": event, "matches": matches}

    with tempfile.TemporaryDirectory(prefix="cs2-event-tsv-") as temporary:
        normalized_path = Path(temporary) / f"{event_slug}.json"
        normalized_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return import_event(normalized_path, data_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Import a manually transcribed event TSV without fetching pages."
    )
    parser.add_argument("event_metadata", type=Path, help="JSON object containing event fields")
    parser.add_argument("matches_tsv", type=Path, help="tab-separated match rows")
    arguments = parser.parse_args()

    try:
        destination = import_event_from_tsv(
            arguments.event_metadata,
            arguments.matches_tsv,
        )
    except (OSError, ValidationError) as exc:
        raise SystemExit(f"event TSV import failed: {exc}") from exc
    print(f"Imported and validated event: {destination}")


if __name__ == "__main__":
    main()
