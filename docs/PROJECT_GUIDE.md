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

Follow **Plan → Implement → Trim → Review** and the role permissions in
[AGENTS.md](../AGENTS.md).

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

Use the commands in the README's Quick start.

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

Next, add a small, well-sourced match history and evaluate Elo chronologically.
Add model inputs and features when they can be tested against relevant data;
defer tournament, fantasy, and machine-learning work until then.
