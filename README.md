# CS2 Predictions

A small Counter-Strike 2 match and tournament prediction project.

Right now it provides sourced-data validation, a SQLite data loader, and a
point-in-time Elo backtest. Tournament simulation and fantasy predictions are
planned, not implemented.

## Quick start

Run these commands from this directory:

```text
python -m src.validate
python -m src.load
python -m src.backtest
python -m unittest discover -s tests
```

`data/entities.csv` and the files under `data/raw/` are the active source of
truth. `data/pending/` holds records excluded until HLTV review is complete.
`data/cs.db` is generated and can be rebuilt at any time.

See [the project and data guide](docs/PROJECT_GUIDE.md) for data formats,
validation rules, and the roadmap. See [AGENTS.md](AGENTS.md) for the
contribution workflow.
