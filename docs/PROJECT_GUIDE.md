# Project and data guide

See the root `README.md` for the short project overview and quick start.

The current goal is reliable historical results and a point-in-time Elo
baseline. HLTV is the canonical source for active event and match facts.
`data/cs.db` is generated from validated files; pending events are excluded.

## Layout

- `data/entities.csv` — stable team/player IDs and sourced name aliases.
- `data/raw/<event-id>.json` — normalized event records.
- `data/pending/` — preserved event records awaiting HLTV verification.
- `data/source/<event-id>/` — optional captures when source terms permit them.
- `data/reports/` — generated coverage and discrepancy reports.
- `data/raw/roster_stints.csv` — dated lineup history, entered separately from
  event results.
- `data/cs.db` — generated normalized database; never edit it directly.
- `src/validate.py` — reads and validates source files without changing them.
- `src/load.py` — rebuilds SQLite from validated sources.
- `src/schema.sql` — database table and constraint definitions.
- `src/elo.py` — Elo probabilities, updates, and Brier scoring.
- `src/backtest.py` — reads historical matches from SQLite and runs the
  chronological Elo evaluation.
- `tests/` — focused validation, loader, and model tests.
- `docs/PROJECT_GUIDE.md` — detailed data contracts and project roadmap.
- `AGENTS.md` — repository rules for contributors and coding agents.

## Contribution workflow

Follow **Plan → Implement → Trim → Review** and the role permissions in
[AGENTS.md](../AGENTS.md).

## Source data

### Source selection and collection

For event and match results, roster moves, and other currently modeled facts,
prefer direct official sources such as event organizers and team announcements.
Reputable structured sources may also be used when they publish the relevant
fact and allow the intended collection method. A page being public does not by
itself permit scraping. Check the source's current terms and API documentation
before automating collection; follow stated limits and do not bypass access
controls. If permission is unclear, use a permitted manual method or ask a
human.

HLTV is a primary source. Liquipedia may be used as an optional manual or
approved-API cross-check; API use requires user-confirmed approval and must
follow the [Liquipedia API terms](https://liquipedia.net/api-terms-of-use) and
[documentation](https://liquipedia.net/api).

Record direct source URLs, retrieval date, and verifier for each event batch.
Keep team, event, and player-at-event facts distinct. Never guess or invent a
citation. If sources conflict or a required fact cannot be supported, leave
the event pending and ask a human rather than choosing a source automatically.
For time-varying facts, record effective and known dates when they differ.
Plan a schema change if the current format cannot preserve this information.

### Entity registry

`data/entities.csv` has one row per name/alias:

| Column | Meaning |
| --- | --- |
| `entity_type` | `team` or `player`. |
| `entity_id` | Stable readable ID such as `team:vitality` or `player:zywoo`. |
| `canonical_name` | Preferred display name; consistent across rows for an ID. |
| `alias` | A name as it may appear in an event or roster file. |
| `source_url` | Direct reference supporting the identity or alias. |

Add the canonical name as one of the aliases. Alias matching ignores case and
surrounding/repeated whitespace. Aliases cannot map to multiple IDs of the same
type. Unknown names stop the load; the loader never invents entity IDs.
Known spelling variants must be listed as aliases; validation does not guess
fuzzy matches.

### Event files

Each `data/raw/<event-id>.json` contains the event and its match records.
`event-id` in the filename must match the JSON `event.event_id`.

```json
{
  "event": {
    "event_id": "event:sample-major-2026",
    "name": "Sample Major",
    "tier": "S",
    "is_lan": true,
    "format": "Swiss",
    "start_date": "2026-01-01",
    "end_date": "2026-01-10",
    "is_major": true,
    "source_url": "https://www.hltv.org/events/1234/sample-major"
  },
  "matches": [
    {
      "match_id": "match:sample-major-2026-001",
      "date": "2026-01-02",
      "round": "Swiss round 1",
      "team_a": "Vitality",
      "team_b": "NAVI",
      "score_a": 2,
      "score_b": 1,
      "best_of": 3,
      "source_url": "https://www.hltv.org/matches/1234/team-a-vs-team-b",
      "maps": [
        {
          "map_name": "Mirage",
          "score_a": 13,
          "score_b": 8,
          "player_ratings": [{"player": "ZywOo", "rating": 1.31}]
        },
        {"map_name": "Nuke", "score_a": 10, "score_b": 13},
        {"map_name": "Inferno", "score_a": 13, "score_b": 9}
      ],
      "player_ratings": [{"player": "ZywOo", "rating": 1.27}],
      "veto_actions": [
        {"action": "pick", "team": "Vitality", "map_name": "Mirage"},
        {"action": "ban", "team": "NAVI", "map_name": "Ancient"}
      ]
    }
  ]
}
```

Event fields describe the event window, tier, LAN status, format, and major
status. Match team names are aliases from `entities.csv`. `round` is optional;
it retains the published round label. A series between the same teams on the
same date is rejected even when the round labels differ. Match IDs and match
source URLs must be unique.

`provenance` is required and records the retrieval date and verifier.
`source_capture_files` is optional and may only be used when retaining a
capture is permitted. Optional event fields `teams` and
`expected_match_count` let validation check the expected participant roster
and total series count. Each team must appear in at least one match.

The provenance and optional fields have these shapes:

```json
{
  "event": {
    "teams": ["Vitality", "NAVI"],
    "expected_match_count": 1,
    "provenance": {
      "retrieved_on": "2026-11-27",
      "verified_by": "human reviewer"
    }
  },
  "matches": [
    {
      "cross_check": {
        "date": "2026-01-02",
        "team_a": "Vitality",
        "team_b": "NAVI",
        "score_a": 2,
        "score_b": 1,
        "best_of": 3,
        "source_url": "https://liquipedia.net/counterstrike/matches/1234",
        "retrieved_on": "2026-11-27",
        "verified_by": "human reviewer"
      }
    }
  ]
}
```

Event-level provenance is required. A Liquipedia `cross_check` is optional;
when present, it records the compared result, URL, retrieval date, and
verifier. Captures are optional. Disagreements are written to
`data/reports/discrepancies.json` and stop validation until a human checks
HLTV and records the resolution in `event.discrepancy_resolutions`.

Tournament structure is not validated. Stage metadata remains in raw event
files but is not loaded into the database.

The validator writes `data/reports/coverage.json` with event sources, series
and cross-check counts, discrepancies and resolutions, and provenance. All
primary event, match, entity, and roster source URLs must use HTTPS.

Map results are optional. If entered, include all maps played and ensure their
individual winners agree with the series score. `veto_actions` is also
optional; each recorded pick or ban includes its order, acting team, and map.
Player ratings are optional at both series and map level. Each rating entry
contains a registered player name and the HLTV rating shown for that scope.
The loader stores these separately in `player_series_ratings` and
`player_map_ratings`; map ratings require the corresponding map result. Record
ratings by manually reviewing the direct HLTV match page; the pipeline never
fetches or parses HLTV pages. These values are not currently used by Elo.
Unknown JSON fields other than the supported `player_ratings` fields generate
a warning and are skipped by the current loader; source files remain unchanged.

### Sourced match history

IEM Cologne Major 2026 Stages 1 and 2 are active in `data/raw/` with 33
HLTV-linked series each. IEM Chengdu 2025 remains in `data/pending/` until its
event metadata is verified against HLTV.

### Adding more history

Add one event at a time. Verify each fact against a source that supports it and
permits the collection method, record direct URLs plus event retrieval date
and verifier, and retain only source captures that are permitted. Use
structured feeds or APIs to streamline collection only when their terms allow
it. HLTV is the main source of truth. Use Liquipedia as an
optional permitted cross-check. Resolve disagreements through human review;
otherwise leave the event pending. After each batch, run the README checks and
review coverage and backtest results.

For an existing normalized JSON export, run
`python -m src.import_event event.json`, replacing `event.json` with the file's
path. The importer reads a local file only, validates it against the current
entity registry and event data, refuses to overwrite an existing event, and
adds it to `data/raw/`. Register unknown team or player aliases in
`data/entities.csv` first.

### Roster history

`data/raw/roster_stints.csv` has one row per player/team stint:

| Column | Meaning |
| --- | --- |
| `team`, `player` | Names resolved through the entity registry. |
| `start_date` | First date on the team, inclusive. |
| `end_date` | Last date on the team, inclusive; blank for an active stint. |
| `is_stand_in` | `true` or `false`. |
| `known_at` | Date the roster information became available from the cited source. |
| `source_url` | Direct reference for the roster fact. |

Roster dates are stored independently from event files because lineups change
on their own timeline. The current Elo calculation does not yet use roster
stints. Future historical features must filter by `known_at` before the match
date, not merely by the roster's effective dates.

## Database and commands

The rebuild creates only tables needed for current match and roster work:
`teams`, `team_aliases`, `players`, `player_aliases`, `events`, `matches`,
`maps`, `map_results`, `player_series_ratings`, `player_map_ratings`,
`veto_actions`, and `roster_stints`. Other domains (rankings, fantasy, crowd
picks, intangibles, roles, and prediction logs) remain deferred until there is
a concrete use.

The rebuild validates every source before writing a temporary database, checks
SQLite integrity, then atomically replaces `data/cs.db`. A failed validation
leaves the previous database and all raw files untouched.

Use the commands in the README's Quick start.

The validator rejects unknown aliases, same-day duplicate series, team
self-matches, matches outside the event window, invalid series scores, and
map results that do not agree with the series. It compares all supplied
second-source assertions, writes mismatches before stopping, and records
human resolutions. Keep source records and evaluation data
chronological: each match prediction may use only information known before
that match date. For time-varying facts, store both the effective date and
when the fact became known when those differ. Date fields already carry year
information; do not split the raw store into yearly files.

## Current model and roadmap

The baseline starts teams at `1500`, uses LAN/online weights, series margin,
and 180-day rating decay, and predicts all matches on a date before applying
that date's results.

IEM Cologne Major 2026 Stages 1 and 2 are active historical data. Player
ratings are supported but have not yet been populated. The backtest currently
uses series results only; it does not use map or player ratings.

Final ratings describe the latest recorded match, not current form, and Elo
does not use roster stints.

### Player-feature research (deferred)

The user reported (2026-11-27) 29 HLTV Brain player-at-event metrics across
entrying, trading, opening, closing, sniping, and utility. Treat these as a
research lead, not an approved feature set; verify definitions and role
filters with a human-provided sample before designing storage or model changes.
