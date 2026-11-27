# Temporary PR handoff: team aliases before batch ingestion

Delete this file when the PR merges or closes. Keep lasting data contracts in
`docs/PROJECT_GUIDE.md`.

## Goal

Make team identity resolution a prerequisite for the next historical-data
batch. Every input team name must resolve to a stable team ID before data is
loaded, preventing the same team from appearing under duplicate IDs.

## Current baseline

- `data/entities.csv` already stores stable team IDs and sourced aliases.
- `src/validate.py` normalizes alias matching and rejects unknown team names.
- `src/load.py` validates sources before rebuilding and replacing the database.
- `tests/test_data.py` covers alias resolution and verifies that an unknown
  team name fails without replacing the existing database.

## Scope

- Before adding the next batch, compare every team name in its source records
  with the entity registry.
- Add each source-supported name as an alias for the existing team ID when it
  is the same team. Add a new stable ID only when the team is genuinely new;
  include its canonical name as an alias.
- Keep unknown-name handling strict. Do not create teams automatically during
  validation or loading.
- Extend focused tests only if the incoming names expose a behavior not covered
  by the current alias-resolution and unknown-name tests.

## Non-goals

- Implementing the batch import process or adding unsourced aliases.
- Changing the database schema or editing generated `data/cs.db` directly.
- Changing event, match, or roster formats.

## Validation

Run `python -m src.validate` and `python -m unittest discover -s tests`.
After the batch source files are available, rebuild with `python -m src.load`
and confirm that all referenced teams resolve to the intended stable IDs.

## Before merge

- Confirm every team name in scope has a source-backed registry entry.
- Confirm aliases for the same team resolve to one stable ID and unknown names
  still fail before the database is replaced.
- Record any newly added team coverage in `docs/PROJECT_GUIDE.md` if the batch
  is included in this PR.
- Remove this temporary handoff after the PR closes.
