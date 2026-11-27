import csv
import json
import re
import warnings
from datetime import date
from pathlib import Path
from pathlib import PurePosixPath
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


def _hltv_source_url(value, location):
    value = _source_url(value, location)
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not (
        host == "hltv.org" or host.endswith(".hltv.org")
    ):
        _fail(location, "must be an HTTPS HLTV URL")
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
        source_url = _hltv_source_url(row["source_url"], f"{location} source_url")

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


def _source_capture(value, data_dir, event_slug, location):
    value = _text(value, location)
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in value
        or relative.parts[:2] != ("source", event_slug)
    ):
        _fail(
            location,
            f"must be a relative path under source/{event_slug}/",
        )
    try:
        data_root = data_dir.resolve()
        source_root = (data_root / "source" / event_slug).resolve()
        capture = data_root.joinpath(*relative.parts).resolve()
        source_root.relative_to(data_root)
        capture.relative_to(source_root)
    except (OSError, RuntimeError, ValueError):
        _fail(
            location,
            f"source capture {value!r} must resolve within source/{event_slug}/",
        )
    if not capture.is_file():
        _fail(location, f"source capture {value!r} is missing")
    return value


def _load_provenance(raw, data_dir, event_slug, location):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _fail(location, "must be an object")
    allowed = {"retrieved_on", "verified_by", "source_capture_files"}
    _warn_unknown(raw, allowed, location)
    retrieved_on = _date(raw.get("retrieved_on"), f"{location} retrieved_on")
    verified_by = _text(raw.get("verified_by"), f"{location} verified_by")
    capture_files = raw.get("source_capture_files", [])
    if not isinstance(capture_files, list):
        _fail(f"{location} source_capture_files", "must be a list when provided")
    captures = [
        _source_capture(
            value,
            data_dir,
            event_slug,
            f"{location} source_capture_files[{index}]",
        )
        for index, value in enumerate(capture_files)
    ]
    if len(captures) != len(set(captures)):
        _fail(f"{location} source_capture_files", "contains duplicates")
    return {
        "retrieved_on": retrieved_on,
        "verified_by": verified_by,
        "source_capture_files": captures,
    }


def _load_cross_check(match, aliases, data_dir, event_slug, location, primary_url):
    raw = match.get("cross_check")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _fail(f"{location} cross_check", "must be an object")
    fields = {
        "date",
        "team_a",
        "team_b",
        "score_a",
        "score_b",
        "best_of",
        "source_url",
        "retrieved_on",
        "verified_by",
    }
    if "source_capture_file" in raw:
        fields.add("source_capture_file")
    _warn_unknown(raw, fields, f"{location} cross_check")
    checked_date = _date(raw.get("date"), f"{location} cross_check date")
    team_a_id = _resolve_name(
        raw.get("team_a"), aliases, "team", f"{location} cross_check team_a"
    )
    team_b_id = _resolve_name(
        raw.get("team_b"), aliases, "team", f"{location} cross_check team_b"
    )
    if team_a_id == team_b_id:
        _fail(f"{location} cross_check", "a team cannot play itself")
    checked_scores = []
    for field in ("score_a", "score_b", "best_of"):
        value = raw.get(field)
        if type(value) is not int or value < 0:
            _fail(
                f"{location} cross_check {field}",
                "must be a non-negative integer",
            )
        checked_scores.append(value)
    checked_a, checked_b, checked_best_of = checked_scores
    if checked_best_of == 0 or checked_best_of % 2 == 0:
        _fail(f"{location} cross_check", "best_of must be a positive odd integer")
    checked_wins_needed = checked_best_of // 2 + 1
    if (
        checked_a == checked_b
        or max(checked_a, checked_b) != checked_wins_needed
        or min(checked_a, checked_b) >= checked_wins_needed
    ):
        _fail(f"{location} cross_check", "series score is not plausible")

    source_url = _source_url(
        raw.get("source_url"), f"{location} cross_check source_url"
    )
    primary_host = (urlparse(primary_url).hostname or "").casefold().removeprefix("www.")
    checked_host = (urlparse(source_url).hostname or "").casefold().removeprefix("www.")
    if checked_host == primary_host:
        _fail(
            f"{location} cross_check source_url",
            "must use an independent source host",
        )
    if checked_host != "liquipedia.net" and not checked_host.endswith(
        ".liquipedia.net"
    ):
        _fail(
            f"{location} cross_check source_url",
            "must use a Liquipedia backup URL",
        )
    retrieved_on = _date(
        raw.get("retrieved_on"), f"{location} cross_check retrieved_on"
    )
    verified_by = _text(
        raw.get("verified_by"), f"{location} cross_check verified_by"
    )
    capture_value = raw.get("source_capture_file")
    capture_file = (
        _source_capture(
            capture_value,
            data_dir,
            event_slug,
            f"{location} cross_check source_capture_file",
        )
        if capture_value is not None
        else None
    )
    cross_check = {
        "date": checked_date,
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "score_a": checked_a,
        "score_b": checked_b,
        "best_of": checked_best_of,
        "source_url": source_url,
        "retrieved_on": retrieved_on,
        "verified_by": verified_by,
        "source_capture_file": capture_file,
    }
    return cross_check


def _load_team_list(values, aliases, location):
    if not isinstance(values, list) or not values:
        _fail(location, "must be a non-empty list")
    team_ids = [
        _resolve_name(value, aliases, "team", f"{location}[{index}]")
        for index, value in enumerate(values)
    ]
    if len(team_ids) != len(set(team_ids)):
        _fail(location, "contains duplicate teams")
    return team_ids


def _compare_cross_check(match, cross_check, event_id):
    if cross_check is None:
        return []
    discrepancies = []
    for field in ("date", "best_of"):
        if match[field] != cross_check[field]:
            discrepancies.append(
                {
                    "match_id": match["match_id"],
                    "event_id": event_id,
                    "field": field,
                    "primary": match[field],
                    "cross_check": cross_check[field],
                    "primary_source_url": match["source_url"],
                    "cross_check_source_url": cross_check["source_url"],
                }
            )

    primary_score_by_team = {
        match["team_a_id"]: match["score_a"],
        match["team_b_id"]: match["score_b"],
    }
    checked_score_by_team = {
        cross_check["team_a_id"]: cross_check["score_a"],
        cross_check["team_b_id"]: cross_check["score_b"],
    }
    if set(primary_score_by_team) == set(checked_score_by_team):
        for team_id in primary_score_by_team:
            if primary_score_by_team[team_id] != checked_score_by_team[team_id]:
                discrepancies.append(
                    {
                        "match_id": match["match_id"],
                        "event_id": event_id,
                        "field": f"score:{team_id}",
                        "primary": primary_score_by_team[team_id],
                        "cross_check": checked_score_by_team[team_id],
                        "primary_source_url": match["source_url"],
                        "cross_check_source_url": cross_check["source_url"],
                    }
                )
    else:
        discrepancies.append(
            {
                "match_id": match["match_id"],
                "event_id": event_id,
                "field": "teams",
                "primary": sorted(primary_score_by_team),
                "cross_check": sorted(checked_score_by_team),
                "primary_source_url": match["source_url"],
                "cross_check_source_url": cross_check["source_url"],
            }
        )
    return discrepancies


def _load_event(path, data_dir, aliases, seen):
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
    if event.get("stages") or any(
        isinstance(match, dict)
        and ("stage" in match or "round_number" in match)
        for match in matches
    ):
        warnings.warn(
            f"{path}: stage metadata is retained in raw data but is not loaded "
            "or validated",
            UserWarning,
            stacklevel=2,
        )

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
        "teams",
        "expected_match_count",
        "stages",
        "provenance",
        "discrepancy_resolutions",
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
        "source_url": _hltv_source_url(
            event.get("source_url"), f"{path} event source_url"
        ),
    }
    expected_teams = None
    if "teams" in event:
        expected_teams = _load_team_list(
            event["teams"], aliases, f"{path} event teams"
        )
    expected_match_count = event.get("expected_match_count")
    if expected_match_count is not None and (
        type(expected_match_count) is not int or expected_match_count < 1
    ):
        _fail(
            f"{path} event expected_match_count",
            "must be a positive integer",
        )

    provenance = _load_provenance(
        event.get("provenance"),
        data_dir,
        expected_stem,
        f"{path} event provenance",
    )
    if provenance is None:
        _fail(path, "event provenance is required")

    raw_resolutions = event.get("discrepancy_resolutions", [])
    if not isinstance(raw_resolutions, list):
        _fail(f"{path} event discrepancy_resolutions", "must be a list")
    resolutions = []
    for index, raw_resolution in enumerate(raw_resolutions):
        resolution_location = f"{path} event discrepancy_resolutions[{index}]"
        if not isinstance(raw_resolution, dict):
            _fail(resolution_location, "must be an object")
        _warn_unknown(
            raw_resolution,
            {"match_id", "resolved_on", "resolved_by", "resolution"},
            resolution_location,
        )
        resolutions.append(
            {
                "match_id": _identifier(
                    raw_resolution.get("match_id"),
                    "match",
                    f"{resolution_location} match_id",
                ),
                "resolved_on": _date(
                    raw_resolution.get("resolved_on"),
                    f"{resolution_location} resolved_on",
                ),
                "resolved_by": _text(
                    raw_resolution.get("resolved_by"),
                    f"{resolution_location} resolved_by",
                ),
                "resolution": _text(
                    raw_resolution.get("resolution"),
                    f"{resolution_location} resolution",
                ),
            }
        )
    resolution_by_match = {}
    for resolution in resolutions:
        match_id = resolution["match_id"]
        if match_id in resolution_by_match:
            _fail(path, f"duplicate discrepancy resolution for {match_id}")
        resolution_by_match[match_id] = resolution
    seen["events"].add(event_id)

    normalized_matches = []
    discrepancies = []
    for index, match in enumerate(matches, start=1):
        location = f"{path} matches[{index - 1}]"
        if not isinstance(match, dict):
            _fail(location, "must be an object")
        match_fields = {
            "match_id",
            "date",
            "round",
            "stage",
            "round_number",
            "team_a",
            "team_b",
            "score_a",
            "score_b",
            "best_of",
            "source_url",
            "maps",
            "veto_actions",
            "cross_check",
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
            tuple(sorted((team_a_id, team_b_id))),
        )
        if duplicate_key in seen["match_keys"]:
            _fail(location, "duplicate event/date/team matchup")
        seen["match_keys"].add(duplicate_key)
        source_url = _hltv_source_url(
            match.get("source_url"), f"{location} source_url"
        )
        if source_url in seen["match_sources"]:
            _fail(location, "duplicate match source_url")
        seen["match_sources"].add(source_url)
        seen["matches"].add(match_id)
        cross_check = _load_cross_check(
            match, aliases, data_dir, expected_stem, location, source_url
        )

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
                "cross_check": cross_check,
                "maps": normalized_maps,
                "veto_actions": normalized_veto,
            }
        )
        discrepancies.extend(
            _compare_cross_check(normalized_matches[-1], cross_check, event_id)
        )

    discrepancy_match_ids = {row["match_id"] for row in discrepancies}
    if not set(resolution_by_match) <= discrepancy_match_ids:
        _fail(path, "discrepancy resolution does not match a current discrepancy")
    for discrepancy in discrepancies:
        resolution = resolution_by_match.get(discrepancy["match_id"])
        discrepancy["resolved"] = resolution is not None
        if resolution is not None:
            discrepancy["resolution"] = resolution

    participants = {
        team_id
        for match in normalized_matches
        for team_id in (match["team_a_id"], match["team_b_id"])
    }
    if expected_teams is not None:
        expected_set = set(expected_teams)
        if not participants <= expected_set:
            _fail(path, "match team is not listed in event teams")
        if participants != expected_set:
            _fail(path, "every listed event team must appear in at least one match")
    if expected_match_count is not None and len(normalized_matches) != expected_match_count:
        _fail(
            path,
            f"expected {expected_match_count} matches, found {len(normalized_matches)}",
        )
    cross_checked_count = sum(
        match["cross_check"] is not None for match in normalized_matches
    )
    return {
        "event": event_row,
        "matches": normalized_matches,
        "discrepancies": discrepancies,
        "coverage": {
            "event_id": event_id,
            "sources": sorted(
                {
                    event_row["source_url"],
                    *(
                        match["source_url"]
                        for match in normalized_matches
                    ),
                    *(
                        match["cross_check"]["source_url"]
                        for match in normalized_matches
                        if match["cross_check"] is not None
                    ),
                }
            ),
            "series_count": len(normalized_matches),
            "expected_series_count": expected_match_count,
            "expected_team_count": (
                len(expected_teams) if expected_teams is not None else None
            ),
            "cross_checked_count": sum(
                match["cross_check"] is not None for match in normalized_matches
            ),
            "cross_check_records": [
                {
                    "match_id": match["match_id"],
                    "source_url": match["cross_check"]["source_url"],
                    "retrieved_on": match["cross_check"]["retrieved_on"],
                    "verified_by": match["cross_check"]["verified_by"],
                    "source_capture_file": match["cross_check"]["source_capture_file"],
                }
                for match in normalized_matches
                if match["cross_check"] is not None
            ],
            "discrepancies_found": len(discrepancies),
            "discrepancies_resolved": sum(
                row["resolved"] for row in discrepancies
            ),
            "discrepancy_resolutions": resolutions,
            "provenance_recorded": provenance is not None,
            "provenance": provenance,
        },
    }


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
        source_url = _hltv_source_url(row["source_url"], f"{location} source_url")
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
    coverage, discrepancies = [], []
    seen = {
        "events": set(),
        "matches": set(),
        "match_keys": set(),
        "match_sources": set(),
    }

    for path in sorted(raw_dir.glob("*.json")):
        loaded = _load_event(path, data_dir, aliases, seen)
        events.append(loaded["event"])
        coverage.append(loaded["coverage"])
        discrepancies.extend(loaded["discrepancies"])
        for match in loaded["matches"]:
            matches.append(
                {
                    key: value
                    for key, value in match.items()
                    if key not in {"maps", "veto_actions", "cross_check"}
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

    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    discrepancy_report = reports_dir / "discrepancies.json"
    coverage_report = reports_dir / "coverage.json"
    discrepancy_report.write_text(
        json.dumps(discrepancies, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    coverage_report.write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    unresolved_discrepancies = [
        row for row in discrepancies if not row["resolved"]
    ]
    if unresolved_discrepancies:
        _fail(
            discrepancy_report,
            f"{len(unresolved_discrepancies)} unresolved cross-source "
            "discrepancy(s); "
            "human resolution is required before validation can continue",
        )
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
        "coverage": coverage,
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
    for event in data["coverage"]:
        print(
            f"{event['event_id']}: {event['series_count']} series, "
            f"{event['cross_checked_count']} cross-checked, "
            f"{event['discrepancies_found']} discrepancies."
        )
    print(f"Coverage report: {DATA_DIR / 'reports' / 'coverage.json'}")
    print(f"Discrepancy report: {DATA_DIR / 'reports' / 'discrepancies.json'}")


if __name__ == "__main__":
    main()
