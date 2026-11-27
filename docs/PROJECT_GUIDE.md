# Project and data guide

See the root `README.md` for the short project overview and quick start.

The current goal is reliable historical data collection and a point-in-time
Elo baseline. Event files and the entity registry are the source of truth;
`data/cs.db` is a generated SQLite database rebuilt from them. No real event
history existed before the initial IEM Chengdu 2025 slice was added. The
current evaluation is a small pipeline and baseline check, not evidence of
general predictive quality.

## Layout

- `data/entities.csv` — stable team/player IDs and sourced name aliases.
- `data/raw/<event-id>.json` — normalized event records.
- `data/source/<event-id>/` — unchanged source captures.
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

Use public sources only when their terms permit the intended use. Prefer
official event sources for event facts. As of 2026-11-27, Liquipedia API access
is pending; do not use it until the user confirms approval. Its
[terms](https://liquipedia.net/api-terms-of-use) require approved LiquipediaDB
access, do not support MediaWiki API use for bulk data, and prohibit non-API
HTML automation. If access is granted, follow the
[current API documentation](https://liquipedia.net/api), including its rate
limits and attribution requirements (CC BY-SA 3.0).

Do not automate access to HLTV. For missing details, ask the user or a human;
dictated data is fine. Label it user-provided, record the subject and capture
date, and include the underlying source when known. Never guess or invent a
citation. Respect rate limits, caching, and attribution; never bypass access
limits with proxies, IP changes, stealth tools, or third-party accounts.

Keep team, event, and player-at-event facts distinct. Record source URLs and,
for time-varying facts, both effective and known dates when they differ.
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
it retains the published round label. A series between the same teams on the
same date is rejected even when the round labels differ. Match IDs and match
source URLs must be unique.

Optional event fields `teams` and `expected_match_count` let validation check
the expected participant roster and total series count. Each team must appear
in at least one match. `provenance` records the retrieval date, verifier, and
relative paths to unchanged captures under `data/source/<event-id>/`.

The optional fields have these shapes:

```json
{
  "event": {
    "teams": ["Vitality", "NAVI"],
    "expected_match_count": 1,
    "provenance": {
      "retrieved_on": "2026-11-27",
      "verified_by": "researcher",
      "source_capture_files": ["source/sample-major-2026/results.txt"]
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
        "source_url": "https://independent.example/match",
        "retrieved_on": "2026-11-27",
        "verified_by": "researcher",
        "source_capture_file": "source/sample-major-2026/results.txt"
      }
    }
  ]
}
```

For a complete second-source check, add a `cross_check` object to every match
and event-level `provenance`. It records the second source's date, teams,
series score, best-of, URL, retrieval date, verifier, and capture path. The
second source must have a different host from the match's primary source.
Disagreements are written to `data/reports/discrepancies.json` and stop
validation until a human resolves them. Record the match ID, date, verifier,
and explanation in `event.discrepancy_resolutions`; validation then retains
the discrepancy and its resolution in the report rather than selecting a
source automatically.

Tournament structure is not validated. Stage metadata remains in raw event
files but is not loaded into the database.

The validator writes `data/reports/coverage.json` with event sources, series
and cross-check counts, discrepancies and resolutions, and provenance.
Missing cross-checks or provenance remain visible; legacy event files
continue to load.

Map results are optional. If entered, include all maps played and ensure their
individual winners agree with the series score. `veto_actions` is also
optional; each recorded pick or ban includes its order, acting team, and map.
Unknown JSON fields (including future player-stat blocks) generate a warning
and are skipped by the current loader; source files remain unchanged.

### Sourced match history

The first sourced event is the full IEM Chengdu 2025 event: 16 teams and 30
series from November 3–9, 2025. Event identity and EPT Masters classification
are sourced from the
[official ESL event page](https://pro.eslgaming.com/tour/cs/chengdu/). Dates
and format are cross-checked against the
[HLTV event page](https://www.hltv.org/events/8041/iem-chengdu-2025) and
[BLAST event results](https://blast.tv/cs/tournaments/iem-chengdu-2025/match).
Team identities and individual match records link to direct HLTV team and
match pages in the source files. This slice contains series results only; map
results, rosters, and player statistics are not included. Its existing event
file predates per-series cross-check and retrieval metadata, so coverage
reports 0 explicitly cross-checked series.

IEM Cologne Major 2026 adds 32 teams and 106 series from June 2–21, 2026.
The [ESV results page](https://esport.vision/cs2/tournament/10488-iem-cologne-major-2026)
and [BLAST results page](https://blast.tv/cs/tournaments/iem-cologne-major-2026/match)
were cross-checked for every series. Four Stage 1 Sharks/Dendele name
conflicts were resolved using the user's manual HLTV check, recorded in the
[verification note](../data/source/iem-cologne-major-2026/hltv-stage1-manual-check.txt).
Dendele remains a source-observed alias, not a Major entrant. The sites use
different hosts, but their underlying data lineage is unknown; playoff
best-of values were inferred from series scores. No maps, rosters, or player
statistics are included.

### Adding more history

Add one event at a time. Preserve source captures, cross-check every series
against an independent permitted source, and ask a human to resolve conflicts
or missing facts. After each batch, run the README checks and record coverage
and backtest results.

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

The original IEM Chengdu 2025 slice produced 30 predictions across 16 teams
(November 3–9, 2025), with a Brier score of `0.25006867`. The current
two-event backtest contains 136 predictions across 35 rated teams from
November 3, 2025 through June 21, 2026. Its Brier score is `0.25052297`,
slightly worse than the constant 0.5 baseline (`0.25000000`). This remains a
small exploratory sample, not evidence of predictive quality. Add more
sourced events before adding features; evaluate by time or held-out events.

Final ratings describe the latest recorded match, not current form, and Elo
does not use roster stints.

### Player-feature research (deferred)

The user reported (2026-11-27) 29 HLTV Brain player-at-event metrics across
entrying, trading, opening, closing, sniping, and utility. Treat these as a
research lead, not an approved feature set; verify definitions and role
filters with a human-provided sample before designing storage or model changes.
