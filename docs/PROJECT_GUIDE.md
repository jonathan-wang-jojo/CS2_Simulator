# Project and data guide

See the root `README.md` for the short project overview and quick start.

The current goal is reliable historical data collection and a point-in-time
Elo baseline. Event files and the entity registry are the source of truth;
`data/cs.db` is a generated SQLite database rebuilt from them. No real event
data has been entered yet, so the current tests check the pipeline, not model
quality.

## Layout

- `data/entities.csv` — stable team/player IDs and sourced name aliases.
- `data/raw/<event-id>.json` — one unchanged input file per event.
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

Feature work follows **Plan → Implement → Trim → Review**. The planner is
read-only; implementation stays within the agreed plan; trimming removes
unneeded complexity without adding behavior; review is read-only and verifies
the result. Material choices about scope, schema, destructive edits, or
dependencies are brought back for discussion. See `AGENTS.md` for role
permissions, hand-offs, and the `Plan only:`, `Implement:`, `Trim:`, and
`Review:` request labels.

## Source data

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
    "source_url": "https://example.com/event"
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
      "source_url": "https://example.com/match",
      "maps": [
        {"map_name": "Mirage", "score_a": 13, "score_b": 8},
        {"map_name": "Nuke", "score_a": 10, "score_b": 13},
        {"map_name": "Inferno", "score_a": 13, "score_b": 9}
      ],
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
provide it to distinguish legitimate rematches between the same teams on the
same date. Match IDs and match source URLs must be unique.

Map results are optional. If entered, include all maps played and ensure their
individual winners agree with the series score. `veto_actions` is also
optional; each recorded pick or ban includes its order, acting team, and map.
Unknown JSON fields (including future player-stat blocks) generate a warning
and are skipped by the current loader; source files remain unchanged.

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
`maps`, `map_results`, `veto_actions`, and `roster_stints`. Later domains
(player statistics, rankings, fantasy, crowd picks, intangibles, roles, and
prediction logs) are intentionally absent until there is a concrete use.

The rebuild validates every source before writing a temporary database, checks
SQLite integrity, then atomically replaces `data/cs.db`. A failed validation
leaves the previous database and all raw files untouched.

Run commands from this directory:

```text
python -m src.validate
python -m src.load
python -m src.backtest
python -m unittest discover -s tests
```

The validator rejects unknown aliases, duplicate matches, team self-matches,
matches outside the event window, invalid series scores, and map results that
do not agree with the series. Keep source records and evaluation data
chronological: each match prediction may use only information known before
that match date. For time-varying facts, store both the effective date and
when the fact became known when those differ. Date fields already carry year
information; do not split the raw store into yearly files.

## Current model and roadmap

The Elo baseline starts teams at `1500`, applies LAN/online weights and
rating decay, and predicts all matches on a calendar date before applying any
results from that date. Its Brier score is useful only after sourced historical
matches are entered. Evaluate by time or held-out events, never by random
match splits.

1. **Data foundation:** enter a small, well-sourced historical range and
   verify IDs, match results, maps, and roster dates.
2. **Team strength:** compare Elo with sourced VRS/HLTV snapshots (each with
   an as-of date and known-at date), then test recent form with shrinkage,
   roster stability, map/veto matchups, and best-of records one at a time.
3. **Tournament simulation:** add explicit Swiss/bracket formats once match
   probabilities are evaluated.
4. **Fantasy and pick'ems:** collect player stats only for relevant pools;
   include the provider, rating formula version, and known-at date. Then add
   dated prices, crowd pick rates, projection value, and lineup decisions.
5. **Intangibles:** record sourced hypotheses with as-of and known-at dates
   and a note; test them against out-of-time residuals and retain only small
   effects validated across events.
6. **Machine learning:** defer training until multiple events/seasons of
   consistent, time-stamped data and evaluation results exist.

Add data according to the current model's needs. Match outcomes and roster
stints are the starting facts; enter player stats only when tied to an active
fantasy pool, and add qualitative tags as specific hypotheses arise.
