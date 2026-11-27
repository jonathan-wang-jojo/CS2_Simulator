# Temporary PR handoff: historical match history

Delete this file when the PR merges or closes. Dataset sources and evaluation
details live in `docs/PROJECT_GUIDE.md`.

## Scope

Add the IEM Chengdu 2025 results (16 teams, 30 series) and evaluate the
existing Elo baseline. No model features, schema changes, rosters, maps, or
player statistics.

## Status

Data and review are complete. ESL confirms the event details; match results
were cross-checked against the accessible BLAST results page.

- `python -m src.validate`: passed.
- Temporary database rebuild: 16 teams, 1 event, 30 matches.
- Backtest: 30 predictions; Brier `0.25006867` vs. `0.25000000` baseline.
- `python -m unittest discover -s tests`: 11 tests passed.

## Before merge

Keep the broader agent-workflow and source-policy changes separate from this
data PR if the PR is limited to historical match history. Remove this handoff
after the PR closes.
