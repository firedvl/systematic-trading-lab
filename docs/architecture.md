# Architecture

The system is a sequence of explicit authorities:

```text
provider -> raw snapshot -> normalize/validate -> immutable dataset/catalog
        -> strategy target -> portfolio -> simulator
        -> qualification -> independent risk -> order manager -> paper broker
        -> broker events -> reconciliation -> append-only evidence
```

Only the first line exists now. Strategies will share semantics across backtest, replay, shadow, and paper, but produce targets or intents rather than orders. Qualification remains separate from strategy code. Risk and order management independently reject unsafe intents. UTC is internal time; money and prices use `Decimal`; dataset evidence is content addressed and catalog metadata is reconstructible from manifests.

Runtime data lives under `TRADING_LAB_HOME`: `datasets/<fingerprint>/manifest.json`, `datasets/<fingerprint>/bars.jsonl`, `quarantine/`, and `catalog.sqlite3`. Artifact files are authoritative; SQLite is an index. No broker module exists in the current phase.
