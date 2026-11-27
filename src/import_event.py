import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from src.validate import DATA_DIR, ID_PATTERN, ValidationError, validate_sources


def import_event(source_path, data_dir=DATA_DIR):
    source_path = Path(source_path)
    data_dir = Path(data_dir)
    try:
        source_bytes = source_path.read_bytes()
        document = json.loads(source_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"{source_path}: cannot read event JSON: {exc}"
        ) from exc

    event = document.get("event") if isinstance(document, dict) else None
    event_id = event.get("event_id") if isinstance(event, dict) else None
    if (
        not isinstance(event_id, str)
        or not ID_PATTERN.fullmatch(event_id)
        or not event_id.startswith("event:")
    ):
        raise ValidationError(
            f"{source_path}: event.event_id must be a valid event ID"
        )

    event_slug = event_id.split(":", 1)[1]
    raw_dir = data_dir / "raw"
    destination = raw_dir / f"{event_slug}.json"
    if destination.exists():
        raise FileExistsError(f"event destination already exists: {destination}")

    with tempfile.TemporaryDirectory(prefix="cs2-event-import-") as temporary:
        staged_data_dir = Path(temporary) / "data"
        staged_data_dir.mkdir()
        shutil.copy2(data_dir / "entities.csv", staged_data_dir / "entities.csv")
        shutil.copytree(raw_dir, staged_data_dir / "raw")
        source_dir = data_dir / "source"
        if source_dir.is_dir():
            shutil.copytree(source_dir, staged_data_dir / "source")

        staged_destination = staged_data_dir / "raw" / destination.name
        staged_destination.write_bytes(source_bytes)
        validate_sources(staged_data_dir)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{event_slug}.",
        suffix=".tmp",
        dir=raw_dir,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_bytes(source_bytes)
        os.link(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    try:
        validate_sources(data_dir)
    except (OSError, ValidationError):
        destination.unlink()
        raise

    return destination


def main():
    parser = argparse.ArgumentParser(
        description="Import and validate a local normalized event JSON file."
    )
    parser.add_argument("json_file", type=Path, help="path to the event JSON export")
    arguments = parser.parse_args()

    try:
        destination = import_event(arguments.json_file)
    except (OSError, ValidationError) as exc:
        raise SystemExit(f"event import failed: {exc}") from exc
    print(f"Imported and validated event: {destination}")


if __name__ == "__main__":
    main()
