# Architecture

The system is a sequence of explicit authorities:

```text
provider -> raw snapshot -> normalize/validate -> immutable dataset/catalog
        -> strategy target -> portfolio -> simulator
        -> qualification -> independent risk -> order manager -> paper broker
        -> broker events -> reconciliation -> append-only evidence
```

The data and simulation lines now exist for deterministic daily-bar research. Strategies share semantics across backtest, replay, shadow, and paper, but produce targets or intents rather than orders. A separate SQLite registry owns campaign budgets, experiment lifecycle, recovery, split classification, and qualification evidence. The experiment runner records and claims each candidate before simulation, then stores its metrics and report fingerprint or its failure. Walk-forward folds and cost or fill-delay variants are separate linked candidates. Qualification remains separate from strategy code. Risk and order management independently reject unsafe intents. UTC is internal time; money and prices use `Decimal`; dataset evidence is content addressed and catalog metadata is reconstructible from manifests.

Runtime data lives under `TRADING_LAB_HOME`: `datasets/<fingerprint>/manifest.json`, `datasets/<fingerprint>/raw.jsonl`, `datasets/<fingerprint>/bars.parquet`, `quarantine/`, `catalog.sqlite3`, and `experiments.sqlite3`. Dataset artifact files are authoritative; the dataset catalog is an index. The experiment registry is authoritative lifecycle evidence. The Alpaca integration is a read-only HTTP provider; no broker module exists in the current phase.
