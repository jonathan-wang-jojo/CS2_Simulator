# Agent workflow

## Roles

- **Planner (read-only):** Read relevant guidance, code, data, and tests.
  Return a brief plan in docs with goal, scope, files, checks, and open risks. Ask
  before decisions that change scope, data formats, dependencies, or behavior.
- **Implementer:** Make only approved changes and directly needed tests or
  docs. Stop rather than guess when a new design choice appears.
- **Trimmer:** Remove unnecessary additions without changing behavior or
  deleting existing code or source data. Before closing a temporary PR plan,
  move lasting rules and data contracts into permanent docs.
- **Reviewer (read-only):** Check scope, contracts, regressions, and focused
  test results. Report issues; do not fix them.

## Workflow

- Use **Plan → Implement → Trim → Review**. Each stage keeps its own
  responsibilities; do not launch agents just to represent these stages.
- `Plan:` stops after planning. `Implement:` plans first, then proceeds
  when scope is clear. `Trim:` and `Review:` perform only that stage.
- Use a temporary PR plan only for multi-step handoffs. Keep PR-only steps
  there; move lasting project guidance to `AGENTS.md` or
  `docs/PROJECT_GUIDE.md`. Delete the temporary plan after the PR closes.

## Project rules

- Use plain language. Keep additions short and avoid repeating other docs.
- Follow `docs/PROJECT_GUIDE.md` for sources and data contracts. Use permitted
  sources, keep provenance, and ask a human rather than guessing or bypassing
  access limits.
- Keep `data/entities.csv` and `data/raw/` as source files. Never edit
  generated `data/cs.db` directly. Change `src/schema.sql` and document schema
  changes in the guide.
- Keep work focused and avoid speculative features. Run tests with
  `python -m unittest discover -s tests`; report exactly what was run.
- Historical predictions may use only information known before the prediction.
