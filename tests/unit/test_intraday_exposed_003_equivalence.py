from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

import systematic_trading_lab.intraday_exposed_003_equivalence as equivalence_module
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.intraday_exposed_003_equivalence import (
    _load_fixtures,
    _Replay,
    _require_equivalent,
    verify_intraday_exposed_003_parallel_equivalence,
)
from systematic_trading_lab.intraday_exposed_003_runner import DATABASE_NAME, _run_id
from systematic_trading_lab.research_attempts import ResearchAttemptStore

_SOURCE_SHA = "a" * 40


def _specification(candidate: str, family: str, scenario: str) -> dict[str, object]:
    return {
        "schema_version": "intraday-exposed-003-run-v1",
        "program_id": "intraday-exposed-003",
        "source_commit": _SOURCE_SHA,
        "context": {
            "stage": "discovery",
            "base_candidate_id": None,
            "candidate_id": candidate,
            "family_id": family,
            "period_id": "discovery-2025-07-through-10",
            "scenario_id": scenario,
        },
    }


def _report(specification: dict[str, object], metric: int) -> tuple[bytes, str]:
    payload: dict[str, object] = {
        "schema_version": "intraday-exposed-003-backtest-report-v1",
        "program_id": "intraday-exposed-003",
        "run_id": _run_id(specification),
        "specification": specification,
        "specification_fingerprint": fingerprint(specification),
        "metrics": {"test_metric": metric},
        "details": {
            "fill_trace_fingerprint": fingerprint({"fills": metric}),
            "round_trip_fingerprint": fingerprint({"trades": metric}),
        },
    }
    report_fingerprint = fingerprint(payload)
    return (
        canonical_json({**payload, "report_fingerprint": report_fingerprint}) + "\n"
    ).encode(), (report_fingerprint)


def _database(root: Path, metrics: tuple[int, ...]) -> Path:
    specifications = (
        _specification("ie003-f01-a01-b01", "family-a", "normal"),
        _specification("ie003-f01-a01-b01", "family-a", "zero_cost_diagnostic"),
        _specification("ie003-f02-a01-b01", "family-b", "normal"),
        _specification("ie003-f02-a01-b01", "family-b", "zero_cost_diagnostic"),
        _specification("ie003-f03-a01-b01", "family-c", "normal"),
    )
    store = ResearchAttemptStore(root, database_name=DATABASE_NAME)
    for index, (specification, metric) in enumerate(zip(specifications, metrics, strict=True)):
        run_id = _run_id(specification)
        store.reserve(run_id, specification)
        started = datetime(2026, 8, 22, 12, tzinfo=UTC) + timedelta(seconds=index)
        claim = store.claim(run_id, source_sha=_SOURCE_SHA, started_at=started)
        report, report_fingerprint = _report(specification, metric)
        store.publish(
            claim,
            Path("run-reports") / f"{run_id}.json",
            report,
            report_fingerprint=report_fingerprint,
            finished_at=started + timedelta(milliseconds=1),
            exit_status=0,
        )
    return store.path


def test_fixture_selection_uses_configuration_not_metrics_and_is_read_only(
    tmp_path: Path,
) -> None:
    first = _database(tmp_path / "first", (99, -100, 0, 50, -7))
    second = _database(tmp_path / "second", (-7, 50, 0, -100, 99))
    before = hashlib.sha256(first.read_bytes()).hexdigest()

    first_fixtures = _load_fixtures(first, 4)
    second_fixtures = _load_fixtures(second, 4)

    assert tuple(item.run_id for item in first_fixtures) == tuple(
        item.run_id for item in second_fixtures
    )
    assert len({str(item.specification["context"]) for item in first_fixtures}) == 4
    assert hashlib.sha256(first.read_bytes()).hexdigest() == before


def test_equivalence_rejects_fill_trace_or_metric_drift(tmp_path: Path) -> None:
    database = _database(tmp_path, (1, 2, 3, 4, 5))
    fixture = _load_fixtures(database, 3)[0]
    reference = fixture.report_bytes
    replay = _Replay(
        fixture.run_id,
        fixture.run_fingerprint,
        reference,
        fixture.report_sha256,
        fixture.report_fingerprint,
        "0" * 64,
        "0" * 64,
    )

    with pytest.raises(ValueError, match="deterministic equivalence differs"):
        _require_equivalent(fixture, replay, "four-worker")


def test_parallel_equivalence_requires_more_than_one_worker(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least two workers"):
        verify_intraday_exposed_003_parallel_equivalence(tmp_path, tmp_path, workers=1)


def test_equivalence_detects_source_database_byte_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path / "intraday-exposed-003", (1, 2, 3, 4, 5))
    fixtures = _load_fixtures(database, 3)
    replays: list[_Replay] = []
    for fixture in fixtures:
        report = cast(dict[str, object], json.loads(fixture.report_bytes))
        details = cast(dict[str, object], report["details"])
        replays.append(
            _Replay(
                fixture.run_id,
                fixture.run_fingerprint,
                fixture.report_bytes,
                fixture.report_sha256,
                fixture.report_fingerprint,
                str(details["fill_trace_fingerprint"]),
                str(details["round_trip_fingerprint"]),
            )
        )
    calls = 0

    def run_stage(*_args: object, **_kwargs: object) -> tuple[_Replay, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            with database.open("ab") as handle:
                handle.write(b"mutated")
        return tuple(replays)

    monkeypatch.setattr(equivalence_module, "_source_commit", lambda _repository: _SOURCE_SHA)
    monkeypatch.setattr(equivalence_module, "_dataset_input_hashes", lambda *_args: {})
    monkeypatch.setattr(equivalence_module, "run_process_stage", run_stage)

    with pytest.raises(ValueError, match="database bytes"):
        verify_intraday_exposed_003_parallel_equivalence(
            tmp_path,
            tmp_path,
            workers=4,
            fixture_count=3,
        )
