# Agent workflow

Use this workflow for every feature, cleanup, and review. Roles are sequential
responsibilities, not a requirement to launch separate agents.

## Roles

### Planner — read-only

- Read `README.md`, `docs/PROJECT_GUIDE.md`, this file, and the relevant code,
  data schema, tests, and direct callers before proposing work.
- Search for existing behavior and helpers before recommending new ones.
- State the goal, non-goals, files and dependencies likely affected, risks,
  test plan, alternatives, and unresolved design questions.
- Do not edit files, change data, generate artifacts, or implement the plan.
- Ask before proceeding when a choice affects scope, data format/schema,
  public behavior, destructive changes, or dependencies.

### Implementer — bounded changes

- Implement only the agreed plan. Keep changes small and use existing
  patterns; do not add a feature simply because it is easy to add.
- If inspection reveals a material design choice or out-of-scope issue, stop,
  explain the trade-off, and return it to planning instead of guessing.
- Update focused tests and directly related documentation with behavior or
  schema changes.
- Preserve raw source files. Never edit generated `data/cs.db` directly.

### Trimmer — subtractive pass

- Inspect every file changed by the implementation. Challenge every new
  function, branch, comment, abstraction, dependency, and file: is it needed,
  already available elsewhere, and consistent with this repository?
- Remove redundancy, dead code, unnecessary comments, and avoidable
  indirection while preserving approved behavior.
- Before a major refactor or removal, ask the user what the component is for
  and whether it is still needed; explain dependencies and alternatives,
  especially when files, schemas, or public behavior are affected.
- Do not add features or change the approved behavior during trimming.
- Do not delete pre-existing code or source data without explicit approval.
  If simplification requires a design choice, send it back to planning.

### Reviewer — read-only verification

- Review the final changes against the request, plan, data contracts, and
  existing behavior. Look for regressions, leakage, data loss, and scope
  expansion.
- Run the smallest relevant tests and report exactly what passed or failed.
- Do not edit files. Send discovered issues back to the Implementer; do not
  silently fix them during review.
- Report remaining risks, deliberate trade-offs, deferred work, and useful
  next steps. Separate confirmed bugs from suggestions.

## Cycle and request modes

Default feature work proceeds as **Plan → Implement → Trim → Review**. Re-plan
if implementation reveals a material new choice. If an issue is outside the
approved scope, record it as a follow-up instead of bundling it into the
current change.

Users may request a single mode with these labels:

- `Plan only:` inspect and propose; make no changes.
- `Implement:` plan first, then implement the agreed scope.
- `Trim:` perform only a subtractive pass on the named changes.
- `Review:` perform a read-only review and run relevant checks.

These are request labels, not executable slash commands. Do not launch
multiple agents merely to represent these roles; use separate agents only for
substantial, independent work.

## Always

- Keep the change more useful than its implementation, data, and maintenance
  cost. Prefer broad foundations over speculative feature-specific machinery.
- Read before editing; inspect direct dependencies and call sites; do not
  assume a tagged path exists if it is missing.
- Keep each fact source-traceable and dated. Historical predictions may use
  only information available before the prediction date.
- Keep SQLite rebuildable from `data/entities.csv` and `data/raw/`. Keep
  `README.md` short; update `docs/PROJECT_GUIDE.md` and `src/schema.sql`
  together when documented data contracts change.
- Run tests from this directory with `python -m unittest discover -s tests`.
- Never claim tests, validation, or review passed unless they were run.
