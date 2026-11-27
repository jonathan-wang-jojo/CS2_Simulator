import csv
import json
import re
import warnings
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

REGISTRY_COLUMNS = [
    "entity_type",
    "entity_id",
    "canonical_name",
    "alias",
    "source_url",
]
ROSTER_COLUMNS = [
    "team",
    "player",
    "start_date",
    "end_date",
    "is_stand_in",
    "known_at",
    "source_url",
]
ID_PATTERN = re.compile(r"^(team|player|event|match):[a-z0-9]+(?:-[a-z0-9]+)*$")


class ValidationError(ValueError):
    pass


def _fail(location, message):
    raise ValidationError(f"{location}: {message}")


def _warn_unknown(record, allowed, location):
    for key in sorted(set(record) - set(allowed)):
        warnings.warn(
            f"{location}: unknown field {key!r} ignored; raw data is preserved",
            UserWarning,
            stacklevel=2,
        )


def _text(value, location):
    if not isinstance(value, str) or not value.strip():
        _fail(location, "must be a non-empty string")
    return value.strip()


def _date(value, location):
    value = _text(value, location)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(location, "must be a date in YYYY-MM-DD format")
    if parsed.isoformat() != value:
        _fail(location, "must be a date in YYYY-MM-DD format")
    return value


def _source_url(value, location):
    value = _text(value, location)
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        _fail(location, "must be an http or https source URL")
    return value


def _alias_key(value):
    return " ".join(_text(value, "alias").split()).casefold()


def _identifier(value, kind, location):
    value = _text(value, location)
    if not ID_PATTERN.fullmatch(value) or not value.startswith(f"{kind}:"):
        _fail(location, f"must be a readable {kind}:slug ID")
    return value


def _map_identity(value, location):
    name = _text(value, location)
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not slug:
        _fail(location, "does not produce a valid map ID")
    return f"map:{slug}", name


def _load_csv(path, expected_columns):
    if not path.is_file():
        _fail(path, "file is missing")
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != expected_columns:
            _fail(path, f"expected columns {expected_columns!r}")
        rows = list(reader)
    for line_number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            _fail(f"{path}:{line_number}", "row has missing or extra CSV fields")
    return rows


def _load_registry(path):
    rows = _load_csv(path, REGISTRY_COLUMNS)
    entities = {"team": {}, "player": {}}
    aliases = {"team": {}, "player": {}}
    alias_rows = {"team": [], "player": []}

    for line_number, row in enumerate(rows, start=2):
        location = f"{path}:{line_number}"
        kind = _text(row["entity_type"], f"{location} entity_type").casefold()
        if kind not in entities:
            _fail(f"{location} entity_type", "must be 'team' or 'player'")

        entity_id = _identifier(row["entity_id"], kind, f"{location} entity_id")
        canonical_name = _text(
            row["canonical_name"], f"{location} canonical_name"
        )
        alias = _text(row["alias"], f"{location} alias")
        source_url = _source_url(row["source_url"], f"{location} source_url")

        previous_name = entities[kind].get(entity_id)
        if previous_name is not None and previous_name != canonical_name:
            _fail(location, f"{entity_id} has conflicting canonical names")
        entities[kind][entity_id] = canonical_name

        key = _alias_key(alias)
        previous_id = aliases[kind].get(key)
        if previous_id is not None and previous_id != entity_id:
            _fail(location, f"alias {alias!r} maps to multiple {kind} IDs")
        if previous_id is not None:
            _fail(location, f"duplicate {kind} alias {alias!r}")
        aliases[kind][key] = entity_id
        alias_rows[kind].append(
            {
                "alias_key": key,
                "alias": alias,
                "entity_id": entity_id,
                "source_url": source_url,
            }
        )

    for kind, members in entities.items():
        for entity_id, canonical_name in members.items():
            if aliases[kind].get(_alias_key(canonical_name)) != entity_id:
                _fail(
                    path,
                    f"canonical name {canonical_name!r} for {entity_id} "
                    "must also appear as an alias",
                )

    return entities, aliases, alias_rows


def _resolve_name(value, aliases, kind, location):
    name = _text(value, location)
    entity_id = aliases[kind].get(_alias_key(name))
    if entity_id is None:
        _fail(location, f"unknown {kind} name {name!r}; add it to entities.csv")
    return entity_id


def _load_event(path, aliases, seen):
    try:
        with path.open(encoding="utf-8") as source:
            raw = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        _fail(path, f"cannot read event JSON: {exc}")

    if not isinstance(raw, dict):
        _fail(path, "event file must contain a JSON object")
    _warn_unknown(raw, {"event", "matches"}, path)
    event = raw.get("event")
    matches = raw.get("matches")
    if not isinstance(event, dict):
        _fail(path, "event must be an object")
    if not isinstance(matches, list):
        _fail(path, "matches must be a list")

    event_fields = {
        "event_id",
        "name",
        "tier",
        "is_lan",
        "format",
        "start_date",
        "end_date",
        "is_major",
        "source_url",
    }
    _warn_unknown(event, event_fields, f"{path} event")
    event_id = _identifier(event.get("event_id"), "event", f"{path} event_id")
    if event_id in seen["events"]:
        _fail(path, f"duplicate event ID {event_id}")
    expected_stem = event_id.split(":", 1)[1]
    if path.stem != expected_stem:
        _fail(path, f"filename must be {expected_stem}.json for event {event_id}")

    start_date = _date(event.get("start_date"), f"{path} start_date")
    end_date = _date(event.get("end_date"), f"{path} end_date")
    if end_date < start_date:
        _fail(path, "event end_date is before start_date")
    if type(event.get("is_lan")) is not bool:
        _fail(path, "event is_lan must be true or false")
    if type(event.get("is_major")) is not bool:
        _fail(path, "event is_major must be true or false")

    tier = event.get("tier")
    if isinstance(tier, bool) or not isinstance(tier, (str, int)):
        _fail(path, "event tier must be a non-empty string or integer")
    tier = str(tier).strip()
    if not tier:
        _fail(path, "event tier cannot be empty")

    event_row = {
        "event_id": event_id,
        "name": _text(event.get("name"), f"{path} event name"),
        "tier": tier,
        "is_lan": int(event["is_lan"]),
        "format": _text(event.get("format"), f"{path} event format"),
        "start_date": start_date,
        "end_date": end_date,
        "is_major": int(event["is_major"]),
        "source_url": _source_url(event.get("source_url"), f"{path} event source_url"),
    }
    seen["events"].add(event_id)

    normalized_matches = []
    for index, match in enumerate(matches, start=1):
        location = f"{path} matches[{index - 1}]"
        if not isinstance(match, dict):
            _fail(location, "must be an object")
        match_fields = {
            "match_id",
            "date",
            "round",
            "team_a",
            "team_b",
            "score_a",
            "score_b",
            "best_of",
            "source_url",
            "maps",
            "veto_actions",
        }
        _warn_unknown(match, match_fields, location)

        match_id = _identifier(match.get("match_id"), "match", f"{location} match_id")
        if match_id in seen["matches"]:
            _fail(location, f"duplicate match ID {match_id}")
        match_date = _date(match.get("date"), f"{location} date")
        if not start_date <= match_date <= end_date:
            _fail(location, "match date falls outside the event date range")

        team_a_id = _resolve_name(
            match.get("team_a"), aliases, "team", f"{location} team_a"
        )
        team_b_id = _resolve_name(
            match.get("team_b"), aliases, "team", f"{location} team_b"
        )
        if team_a_id == team_b_id:
            _fail(location, "a team cannot play itself")

        scores = []
        for field in ("score_a", "score_b", "best_of"):
            value = match.get(field)
            if type(value) is not int or value < 0:
                _fail(f"{location} {field}", "must be a non-negative integer")
            scores.append(value)
        score_a, score_b, best_of = scores
        if best_of == 0 or best_of % 2 == 0:
            _fail(location, "best_of must be a positive odd integer")
        wins_needed = best_of // 2 + 1
        if (
            score_a == score_b
            or max(score_a, score_b) != wins_needed
            or min(score_a, score_b) >= wins_needed
        ):
            _fail(location, "series score is not a plausible result for best_of")

        round_name = match.get("round", "")
        if not isinstance(round_name, str):
            _fail(f"{location} round", "must be a string")
        round_name = round_name.strip()
        duplicate_key = (
            event_id,
            match_date,
            round_name,
            tuple(sorted((team_a_id, team_b_id))),
        )
        if duplicate_key in seen["match_keys"]:
            _fail(location, "duplicate event/date/round/team matchup")
        seen["match_keys"].add(duplicate_key)
        source_url = _source_url(match.get("source_url"), f"{location} source_url")
        if source_url in seen["match_sources"]:
            _fail(location, "duplicate match source_url")
        seen["match_sources"].add(source_url)
        seen["matches"].add(match_id)

        raw_maps = match.get("maps", [])
        if not isinstance(raw_maps, list):
            _fail(f"{location} maps", "must be a list")
        normalized_maps = []
        wins_a = wins_b = 0
        map_ids = set()
        for map_number, map_row in enumerate(raw_maps, start=1):
            map_location = f"{location} maps[{map_number - 1}]"
            if not isinstance(map_row, dict):
                _fail(map_location, "must be an object")
            _warn_unknown(
                map_row,
                {"map_name", "score_a", "score_b"},
                map_location,
            )
            map_id, map_name = _map_identity(
                map_row.get("map_name"), f"{map_location} map_name"
            )
            if map_id in map_ids:
                _fail(map_location, f"duplicate map {map_name!r} in series")
            map_ids.add(map_id)
            map_a, map_b = map_row.get("score_a"), map_row.get("score_b")
            for field, value in (("score_a", map_a), ("score_b", map_b)):
                if type(value) is not int or value < 0:
                    _fail(f"{map_location} {field}", "must be a non-negative integer")
            if map_a == map_b:
                _fail(map_location, "a played map cannot end in a tie")
            wins_a += int(map_a > map_b)
            wins_b += int(map_b > map_a)
            normalized_maps.append(
                {
                    "match_id": match_id,
                    "map_number": map_number,
                    "map_id": map_id,
                    "name": map_name,
                    "score_a": map_a,
                    "score_b": map_b,
                }
            )

        if normalized_maps and (
            len(normalized_maps) != score_a + score_b
            or wins_a != score_a
            or wins_b != score_b
        ):
            _fail(location, "map results do not agree with the series score")

        raw_veto = match.get("veto_actions", [])
        if not isinstance(raw_veto, list):
            _fail(f"{location} veto_actions", "must be a list")
        normalized_veto = []
        veto_maps = set()
        for action_number, action_row in enumerate(raw_veto, start=1):
            action_location = f"{location} veto_actions[{action_number - 1}]"
            if not isinstance(action_row, dict):
                _fail(action_location, "must be an object")
            _warn_unknown(
                action_row,
                {"action", "team", "map_name"},
                action_location,
            )
            action = _text(
                action_row.get("action"), f"{action_location} action"
            ).casefold()
            if action not in {"pick", "ban"}:
                _fail(action_location, "action must be 'pick' or 'ban'")
            team_id = _resolve_name(
                action_row.get("team"), aliases, "team", f"{action_location} team"
            )
            if team_id not in {team_a_id, team_b_id}:
                _fail(action_location, "veto team must be in the match")
            map_id, map_name = _map_identity(
                action_row.get("map_name"), f"{action_location} map_name"
            )
            if map_id in veto_maps:
                _fail(action_location, f"map {map_name!r} appears more than once in veto")
            veto_maps.add(map_id)
            normalized_veto.append(
                {
                    "match_id": match_id,
                    "action_number": action_number,
                    "action": action,
                    "map_id": map_id,
                    "map_name": map_name,
                    "team_id": team_id,
                }
            )

        if normalized_maps:
            if any(
                action["action"] == "pick" and action["map_id"] not in map_ids
                for action in normalized_veto
            ):
                _fail(location, "a picked map must also have a played map result")
            if any(
                action["action"] == "ban" and action["map_id"] in map_ids
                for action in normalized_veto
            ):
                _fail(location, "a banned map cannot have a played map result")

        normalized_matches.append(
            {
                "match_id": match_id,
                "event_id": event_id,
                "date": match_date,
                "round_name": round_name,
                "team_a_id": team_a_id,
                "team_b_id": team_b_id,
                "score_a": score_a,
                "score_b": score_b,
                "best_of": best_of,
                "source_url": source_url,
                "maps": normalized_maps,
                "veto_actions": normalized_veto,
            }
        )

    return event_row, normalized_matches


def _load_roster(path, aliases):
    rows = _load_csv(path, ROSTER_COLUMNS)
    stints = []
    seen = set()
    for line_number, row in enumerate(rows, start=2):
        location = f"{path}:{line_number}"
        team_id = _resolve_name(row["team"], aliases, "team", f"{location} team")
        player_id = _resolve_name(
            row["player"], aliases, "player", f"{location} player"
        )
        start_date = _date(row["start_date"], f"{location} start_date")
        known_at = _date(row["known_at"], f"{location} known_at")
        end_date = (row["end_date"] or "").strip()
        if end_date:
            end_date = _date(end_date, f"{location} end_date")
            if end_date < start_date:
                _fail(location, "end_date is before start_date")
        stand_in_value = _text(
            row["is_stand_in"], f"{location} is_stand_in"
        ).casefold()
        if stand_in_value not in {"true", "false"}:
            _fail(f"{location} is_stand_in", "must be 'true' or 'false'")
        source_url = _source_url(row["source_url"], f"{location} source_url")
        stint_key = (team_id, player_id, start_date)
        if stint_key in seen:
            _fail(location, "duplicate roster stint")
        seen.add(stint_key)
        stints.append(
            {
                "team_id": team_id,
                "player_id": player_id,
                "start_date": start_date,
                "end_date": end_date or None,
                "is_stand_in": int(stand_in_value == "true"),
                "known_at": known_at,
                "source_url": source_url,
            }
        )

    by_player_team = {}
    for stint in stints:
        key = (stint["team_id"], stint["player_id"])
        by_player_team.setdefault(key, []).append(stint)
    for player_stints in by_player_team.values():
        player_stints.sort(key=lambda stint: stint["start_date"])
        for previous, current in zip(player_stints, player_stints[1:]):
            if previous["end_date"] is None or current["start_date"] <= previous["end_date"]:
                _fail(path, "roster stints for the same player/team overlap")

    return stints


def validate_sources(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    raw_dir = data_dir / "raw"
    if not raw_dir.is_dir():
        _fail(raw_dir, "raw data directory is missing")

    entities, aliases, alias_rows = _load_registry(data_dir / "entities.csv")
    events, matches, maps, map_results, veto_actions = [], [], {}, [], []
    seen = {
        "events": set(),
        "matches": set(),
        "match_keys": set(),
        "match_sources": set(),
    }

    for path in sorted(raw_dir.glob("*.json")):
        event, event_matches = _load_event(path, aliases, seen)
        events.append(event)
        for match in event_matches:
            matches.append(
                {
                    key: value
                    for key, value in match.items()
                    if key not in {"maps", "veto_actions"}
                }
            )
            for map_row in match["maps"]:
                maps.setdefault(
                    map_row["map_id"],
                    {"map_id": map_row["map_id"], "name": map_row["name"]},
                )
                map_results.append(map_row)
            for action in match["veto_actions"]:
                maps.setdefault(
                    action["map_id"],
                    {"map_id": action["map_id"], "name": action["map_name"]},
                )
            veto_actions.extend(match["veto_actions"])

    roster_stints = _load_roster(raw_dir / "roster_stints.csv", aliases)

    return {
        "entities": entities,
        "aliases": alias_rows,
        "events": events,
        "matches": matches,
        "maps": list(maps.values()),
        "map_results": map_results,
        "veto_actions": veto_actions,
        "roster_stints": roster_stints,
    }


def main():
    try:
        data = validate_sources()
    except (OSError, ValidationError) as exc:
        raise SystemExit(f"validation failed: {exc}") from exc
    print(
        "Validated "
        f"{len(data['events'])} events, {len(data['matches'])} matches, "
        f"{len(data['map_results'])} map results, "
        f"{len(data['roster_stints'])} roster stints."
    )


if __name__ == "__main__":
    main()
