from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.program_002_minute_reconstruction as reconstruction
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.multi_hour_sector_etf_plan import (
    ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH,
    ACCOUNT_ISOLATION_PROOF_REVIEW_RELATIVE_PATH,
    PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_FINGERPRINT,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_FINGERPRINT,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_SHA256,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_SHA256,
    REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT,
    REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
)
from systematic_trading_lab.program_002_acquisition import (
    AcquiredSegment,
    HttpPage,
    Program002AcquisitionError,
    RequestSegment,
    acquire_segment,
)
from systematic_trading_lab.storage import StorageLayout

_REPOSITORY = Path(__file__).resolve().parents[2]


def _plan() -> reconstruction.CompletenessSourcePlan:
    return reconstruction.load_completeness_source_plan(_REPOSITORY)


def _authority() -> reconstruction.SourceAuthority:
    return reconstruction.SourceAuthority(
        Path("source-authority.json"),
        "a" * 64,
        "b" * 64,
        {
            "authority_id": "synthetic-source-authority",
            "acquisition_attempt_id": "synthetic-minute-source-v1",
        },
        Path("source-authority-review.json"),
        "c" * 64,
        "d" * 64,
        {},
    )


def _minute_records(
    segment: RequestSegment,
    *,
    omitted: frozenset[datetime] = frozenset(),
    duplicate_first: bool = False,
    off_grid_first: bool = False,
    missing_trade_count_first: bool = False,
    field_transition_first: bool = False,
) -> list[dict[str, Any]]:
    timestamps = expected_bar_timestamps(
        datetime.fromisoformat(segment.params["start"].replace("Z", "+00:00")),
        datetime.fromisoformat(segment.params["end"].replace("Z", "+00:00")),
        Timeframe.ONE_MINUTE,
    )
    output: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        if timestamp in omitted:
            continue
        price = 100_000 + index
        record: dict[str, Any] = {
            "t": timestamp.isoformat().replace("+00:00", "Z"),
            "o": f"{price / 1000:.3f}",
            "h": f"{(price + 2) / 1000:.3f}",
            "l": f"{(price - 1) / 1000:.3f}",
            "c": f"{(price + 1) / 1000:.3f}",
            "v": index + 1,
            "n": index % 7 + 1,
            "vw": f"{(price + 1) / 1000:.3f}",
        }
        output.append(record)
    if off_grid_first:
        output[0]["t"] = output[0]["t"].replace(":00Z", ":30Z")
    if missing_trade_count_first:
        output[0].pop("n")
    if field_transition_first:
        output[0].pop("vw")
    if duplicate_first:
        output.insert(1, dict(output[0]))
    return output


def _pages(
    segment: RequestSegment,
    **record_options: Any,
) -> tuple[HttpPage, HttpPage]:
    records = _minute_records(segment, **record_options)
    split = len(records) // 2
    bodies = (
        json.dumps(
            {"bars": {"MDY": records[:split]}, "next_page_token": "next"},
            separators=(",", ":"),
        ).encode(),
        json.dumps(
            {"bars": {"MDY": records[split:]}, "next_page_token": None},
            separators=(",", ":"),
        ).encode(),
    )
    return (
        HttpPage(200, bodies[0], {"X-Request-ID": "synthetic-1"}),
        HttpPage(200, bodies[1], {"X-Request-ID": "synthetic-2"}),
    )


def _acquired(
    segment: RequestSegment,
    **record_options: Any,
) -> AcquiredSegment:
    pages = iter(_pages(segment, **record_options))
    return acquire_segment(segment, lambda _: next(pages), pace=lambda: None)


def _sources(plan: reconstruction.CompletenessSourcePlan) -> tuple[AcquiredSegment, ...]:
    return tuple(_acquired(segment) for segment in reconstruction.minute_source_segments(plan))


def _claim(
    layout: StorageLayout,
    plan: reconstruction.CompletenessSourcePlan,
    authority: reconstruction.SourceAuthority,
) -> str:
    return reconstruction._claim_source_attempt(layout, plan, authority)


def _comparators(
    plan: reconstruction.CompletenessSourcePlan,
    sources: tuple[AcquiredSegment, ...],
) -> dict[str, dict[str, Any]]:
    targets = set(plan.payload["exact_derived_coordinates"])
    output: dict[str, dict[str, Any]] = {}
    for acquired in sources:
        rows = reconstruction._validate_source_segment(acquired.segment, acquired)
        for aggregate, _ in reconstruction._aggregate_source_segment(acquired.segment, rows):
            coordinate = f"MDY@{aggregate['timestamp']}"
            if coordinate not in targets:
                output[coordinate] = dict(aggregate)
    return output


def test_frozen_plan_loads_exact_four_request_chains() -> None:
    plan = _plan()
    segments = reconstruction.minute_source_segments(plan)

    assert plan.sha256 == reconstruction._PLAN_SHA256
    assert len(segments) == 4
    assert {segment.params["symbols"] for segment in segments} == {"MDY"}
    assert {segment.params["timeframe"] for segment in segments} == {"1Min"}
    assert {segment.params["feed"] for segment in segments} == {"sip"}
    assert {segment.params["adjustment"] for segment in segments} == {"all"}
    assert all(segment.page_ceiling == 100 for segment in segments)
    assert [segment.params["end"] for segment in segments] == [
        "2021-02-03T20:59:00Z",
        "2021-02-05T20:59:00Z",
        "2021-02-10T20:59:00Z",
        "2021-02-22T20:59:00Z",
    ]


def test_exact_decimal_aggregation_matches_305_controls_and_seven_targets() -> None:
    plan = _plan()
    sources = _sources(plan)
    result = reconstruction.derive_minute_reconstruction(plan, sources, _comparators(plan, sources))

    assert result["source_row_count"] == 1560
    assert result["aggregate_count"] == 312
    assert result["control_match_count"] == 305
    assert result["derived_count"] == 7
    assert {item["symbol"] for item in result["derived_records"]} == {"MDY"}
    assert {item["origin"] for item in result["derived_records"]} == {"provider-derived-from-1m"}
    assert {f"MDY@{item['timestamp']}" for item in result["derived_records"]} == set(
        plan.payload["exact_derived_coordinates"]
    )
    assert len(result["derivation_ledger"]) == 312
    assert all(item["source_minute_coordinates"] for item in result["derivation_ledger"])


def test_comparator_value_or_coordinate_drift_is_terminal() -> None:
    plan = _plan()
    sources = _sources(plan)
    comparators = _comparators(plan, sources)
    coordinate = next(iter(comparators))
    comparators[coordinate]["open"] = "999"
    with pytest.raises(Program002AcquisitionError, match="differs at frozen comparator"):
        reconstruction.derive_minute_reconstruction(plan, sources, comparators)

    comparators = _comparators(plan, sources)
    comparators.pop(next(iter(comparators)))
    with pytest.raises(Program002AcquisitionError, match="coordinate set"):
        reconstruction.derive_minute_reconstruction(plan, sources, comparators)


@pytest.mark.parametrize(
    ("options", "message"),
    (
        ({"duplicate_first": True}, "duplicate minute-source"),
        ({"off_grid_first": True}, "timestamp grid"),
        ({"missing_trade_count_first": True}, "record fields"),
        ({"field_transition_first": True}, "field presence"),
    ),
)
def test_invalid_minute_source_records_fail_closed(options: dict[str, bool], message: str) -> None:
    segment = reconstruction.minute_source_segments(_plan())[0]
    acquired = _acquired(segment, **options)
    with pytest.raises(Program002AcquisitionError, match=message):
        reconstruction._validate_source_segment(segment, acquired)


def test_missing_minutes_are_allowed_only_when_every_bucket_is_nonempty() -> None:
    segment = reconstruction.minute_source_segments(_plan())[0]
    minute_grid = expected_bar_timestamps(
        datetime.fromisoformat(segment.params["start"].replace("Z", "+00:00")),
        datetime.fromisoformat(segment.params["end"].replace("Z", "+00:00")),
        Timeframe.ONE_MINUTE,
    )
    sparse = _acquired(segment, omitted=frozenset({minute_grid[1], minute_grid[2]}))
    rows = reconstruction._validate_source_segment(segment, sparse)
    assert len(reconstruction._aggregate_source_segment(segment, rows)) == 78

    empty_bucket = _acquired(segment, omitted=frozenset(minute_grid[:5]))
    rows = reconstruction._validate_source_segment(segment, empty_bucket)
    with pytest.raises(Program002AcquisitionError, match="bucket is empty"):
        reconstruction._aggregate_source_segment(segment, rows)


def test_source_artifacts_are_create_only_reloadable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    plan = _plan()
    authority = _authority()
    layout = StorageLayout(tmp_path)
    page_queue = iter(
        page for segment in reconstruction.minute_source_segments(plan) for page in _pages(segment)
    )
    first = reconstruction.acquire_minute_sources(
        plan,
        authority,
        layout,
        lambda _: next(page_queue),
        claim_fingerprint=_claim(layout, plan, authority),
        pace=lambda: None,
    )
    assert len(first) == 4
    assert all((layout.dataset(identity) / "segment.json").exists() for identity in first)
    assert set(reconstruction._validate_source_segment_journal(layout, first)) == set(first)
    for identity, segment in zip(first, reconstruction.minute_source_segments(plan), strict=True):
        reconstruction._load_source_segment(
            layout,
            identity,
            plan,
            authority,
            segment,
            authority.payload["acquisition_attempt_id"],
        )

    journal = layout.reports / "program-002" / "minute-source-segments.jsonl"
    original_journal = journal.read_text(encoding="utf-8")
    journal.write_bytes(journal.read_bytes().rstrip(b"\n"))
    assert set(reconstruction._validate_source_segment_journal(layout, first)) == set(first)
    assert journal.read_bytes().endswith(b"\n")
    journal.write_text(original_journal + original_journal.splitlines(keepends=True)[0])
    with pytest.raises(Program002AcquisitionError, match="journal identity"):
        reconstruction._validate_source_segment_journal(layout)
    journal.write_text(original_journal, encoding="utf-8")

    raw_page = layout.dataset(first[0]) / "raw-page-0002.json"
    raw_page.write_bytes(raw_page.read_bytes() + b" ")
    with pytest.raises(Program002AcquisitionError, match="stored minute-source"):
        reconstruction._load_source_segment(
            layout,
            first[0],
            plan,
            authority,
            reconstruction.minute_source_segments(plan)[0],
            authority.payload["acquisition_attempt_id"],
        )


def test_terminal_source_failure_cannot_retry(tmp_path: Path) -> None:
    plan = _plan()
    authority = _authority()
    layout = StorageLayout(tmp_path)
    invalid_pages = iter(
        _pages(
            reconstruction.minute_source_segments(plan)[0],
            missing_trade_count_first=True,
        )
    )
    with pytest.raises(Program002AcquisitionError, match="record fields"):
        reconstruction.acquire_minute_sources(
            plan,
            authority,
            layout,
            lambda _: next(invalid_pages),
            claim_fingerprint=_claim(layout, plan, authority),
            pace=lambda: None,
        )
    assert next(layout.quarantine.glob("*.json"))
    with pytest.raises(Program002AcquisitionError, match="terminal after failure"):
        reconstruction.acquire_minute_sources(
            plan,
            authority,
            layout,
            lambda _: (_ for _ in ()).throw(AssertionError("terminal retry")),
            claim_fingerprint="0" * 64,
            pace=lambda: None,
        )
    terminal = json.loads(
        (layout.reports / "program-002" / "minute-source-terminal-attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    quarantine = layout.quarantine / f"{terminal['quarantine_identity']}.json"
    quarantine.write_bytes(quarantine.read_bytes() + b" ")
    with pytest.raises(Program002AcquisitionError, match="quarantine evidence differs"):
        reconstruction._source_attempt_preflight(
            layout, authority.payload["acquisition_attempt_id"]
        )


def test_source_proof_rederives_frozen_comparators_and_publishes_once(
    tmp_path: Path,
) -> None:
    base_plan = _plan()
    authority = _authority()
    layout = StorageLayout(tmp_path)
    page_queue = iter(
        page
        for segment in reconstruction.minute_source_segments(base_plan)
        for page in _pages(segment)
    )
    source_ids = reconstruction.acquire_minute_sources(
        base_plan,
        authority,
        layout,
        lambda _: next(page_queue),
        claim_fingerprint=_claim(layout, base_plan, authority),
        pace=lambda: None,
    )
    loaded_sources = tuple(
        reconstruction._load_source_segment(
            layout,
            identity,
            base_plan,
            authority,
            segment,
            authority.payload["acquisition_attempt_id"],
        )
        for identity, segment in zip(
            source_ids, reconstruction.minute_source_segments(base_plan), strict=True
        )
    )
    comparators = _comparators(base_plan, loaded_sources)
    raw_records = [
        {
            "symbol": "MDY",
            "t": item["timestamp"],
            "o": item["open"],
            "h": item["high"],
            "l": item["low"],
            "c": item["close"],
            "v": item["volume"],
            "n": item["trade_count"],
            "vw": item["close"],
        }
        for item in comparators.values()
    ]
    evidence = {
        "acquisition_attempt_id": "synthetic-frozen-five-minute-v1",
        "segment_identity": "e" * 64,
        "validation_error": "monthly bar segment validation failed",
        "raw_records": raw_records,
    }
    contents = canonical_json(evidence) + "\n"
    quarantine_identity = "f" * 64
    layout.write_quarantine(quarantine_identity, contents)
    payload = json.loads(json.dumps(dict(base_plan.payload)))
    payload["frozen_runtime_lineage"].update(
        {
            "acquisition_attempt_id": evidence["acquisition_attempt_id"],
            "failed_february_segment_identity": evidence["segment_identity"],
            "failed_february_quarantine_identity": quarantine_identity,
            "failed_february_quarantine_sha256": hashlib.sha256(contents.encode()).hexdigest(),
        }
    )
    plan = replace(base_plan, payload=payload)

    path, proof, created = reconstruction.publish_source_proof(plan, authority, layout, source_ids)
    assert created is True
    assert proof["reconstruction"]["control_match_count"] == 305
    assert proof["reconstruction"]["derived_count"] == 7
    assert proof["strategy_execution_performed"] is False
    assert proof["candidate_returns_generated_or_observed"] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest()

    same_path, same_proof, created = reconstruction.publish_source_proof(
        plan, authority, layout, source_ids
    )
    assert (same_path, same_proof, created) == (path, proof, False)


def test_client_rejects_any_request_outside_four_exact_chains(
    monkeypatch: MonkeyPatch,
) -> None:
    plan = _plan()
    authority = _authority()
    segments = reconstruction.minute_source_segments(plan)
    monkeypatch.setattr(reconstruction, "source_authority_preflight", lambda *_, **__: None)
    seen: list[Request] = []

    def transport(request: Request) -> HttpPage:
        seen.append(request)
        return HttpPage(200, b"{}", {})

    client = reconstruction.MinuteSourceHttpClient(
        "key", "secret", "paper", plan, authority, segments, transport
    )
    assert client.get(segments[0].url()).status == 200
    assert seen[0].method == "GET"
    with pytest.raises(Program002AcquisitionError, match="reviewed scope"):
        client.get(segments[0].url().replace("2021-02-03", "2027-04-16"))


def test_source_authority_cannot_grant_strategy_implementation() -> None:
    authority = {key: False for key in reconstruction._AUTHORITY_KEYS}
    authority.update({"market_data_acquisition": True, "strategy_implementation": True})
    with pytest.raises(Program002AcquisitionError, match="authority flags"):
        reconstruction._verify_source_authority_bindings(
            _REPOSITORY, _plan(), {"authority": authority}
        )


def test_implementation_review_must_bind_exact_authority_source_commit(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    plan = _plan()
    source_files = [
        {
            "path": path,
            "sha256": hashlib.sha256((_REPOSITORY / path).read_bytes()).hexdigest(),
        }
        for path in reconstruction.SOURCE_PATHS
    ]
    reviewed_implementation = {
        "schema_version": "program-002-minute-reconstruction-implementation-review-v1",
        "status": "passed-before-source-authority",
        "verdict": "pass",
        "findings": [],
        "reviewed_implementation": {"source_commit": "b" * 40, "files": source_files},
        "authority": {key: False for key in reconstruction._AUTHORITY_KEYS},
    }
    reviewed_implementation["review_fingerprint"] = fingerprint(reviewed_implementation)
    review_path = tmp_path / "implementation-review.json"
    review_path.write_text(canonical_json(reviewed_implementation) + "\n", encoding="utf-8")
    monkeypatch.setattr(reconstruction, "_IMPLEMENTATION_REVIEW_RELATIVE_PATH", review_path)
    lineage = plan.payload["frozen_runtime_lineage"]
    account_proof = json.loads(
        (_REPOSITORY / ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    authority = {key: False for key in reconstruction._AUTHORITY_KEYS}
    authority["market_data_acquisition"] = True
    payload = {
        "authority": authority,
        "bindings": {
            "completeness_source_plan": {
                "path": reconstruction._PLAN_RELATIVE_PATH.as_posix(),
                "sha256": plan.sha256,
                "fingerprint": plan.fingerprint,
            },
            "completeness_source_plan_review": {
                "path": reconstruction._PLAN_REVIEW_RELATIVE_PATH.as_posix(),
                "sha256": plan.review_sha256,
                "fingerprint": plan.review_fingerprint,
            },
            "provider_contract_evidence": {
                "path": PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
                "fingerprint": REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT,
            },
            "account_isolation_proof": {
                "path": ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_ACCOUNT_ISOLATION_PROOF_SHA256,
                "fingerprint": REVIEWED_ACCOUNT_ISOLATION_PROOF_FINGERPRINT,
            },
            "account_isolation_proof_review": {
                "path": ACCOUNT_ISOLATION_PROOF_REVIEW_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_SHA256,
                "fingerprint": REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_FINGERPRINT,
            },
            "failed_february_quarantine": {
                "identity": lineage["failed_february_quarantine_identity"],
                "sha256": lineage["failed_february_quarantine_sha256"],
            },
            "implementation_review": {
                "path": review_path.as_posix(),
                "sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
                "fingerprint": reviewed_implementation["review_fingerprint"],
            },
        },
        "source_binding": {"source_commit": "a" * 40, "files": source_files},
        "account_isolation": {
            "proof_accepted": True,
            "environment": account_proof["environment"],
            "account_identity_hash": account_proof["account_identity_hash"],
            "credential_key_id_hash": account_proof["credential_key_id_hash"],
        },
        "authorized_requests": [item.url() for item in reconstruction.minute_source_segments(plan)],
        "controls": {
            "raw_source_acquisition": True,
            "source_proof_publication": True,
            "canonical_admission": False,
            "remaining_bar_acquisition": False,
            "quote_acquisition": False,
            "cost_calibration": False,
        },
    }
    with pytest.raises(Program002AcquisitionError, match="implementation review source"):
        reconstruction._verify_source_authority_bindings(_REPOSITORY, plan, payload)


def test_source_attempt_claim_is_atomic(tmp_path: Path) -> None:
    plan = _plan()
    authority = _authority()
    layout = StorageLayout(tmp_path)

    def claim() -> str:
        try:
            return _claim(layout, plan, authority)
        except Program002AcquisitionError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: claim(), range(2)))
    assert sum(item != "blocked" for item in results) == 1
    assert sum(item == "blocked" for item in results) == 1


@pytest.mark.parametrize("failure", ("http", "network"))
def test_source_request_never_retries_and_binds_quarantine(tmp_path: Path, failure: str) -> None:
    plan = _plan()
    authority = _authority()
    layout = StorageLayout(tmp_path / failure)
    calls = 0

    def transport(_: str) -> HttpPage:
        nonlocal calls
        calls += 1
        if failure == "network":
            raise URLError("synthetic network failure")
        return HttpPage(429, b'{"message":"rate limited"}', {"X-Request-ID": "failed"})

    with pytest.raises(Program002AcquisitionError):
        reconstruction.acquire_minute_sources(
            plan,
            authority,
            layout,
            transport,
            claim_fingerprint=_claim(layout, plan, authority),
            pace=lambda: None,
        )
    assert calls == 1
    terminal = json.loads(
        (layout.reports / "program-002" / "minute-source-terminal-attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert terminal["quarantine_identity"]
    assert (layout.quarantine / f"{terminal['quarantine_identity']}.json").exists()


def test_cli_claims_source_attempt_before_credentials(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    plan = _plan()
    authority = _authority()
    order: list[str] = []
    monkeypatch.setattr(reconstruction, "load_completeness_source_plan", lambda _: plan)
    monkeypatch.setattr(reconstruction, "load_source_authority", lambda *_: authority)
    monkeypatch.setattr(reconstruction, "source_authority_preflight", lambda *_: None)
    monkeypatch.setattr(reconstruction, "_source_attempt_preflight", lambda *_: None)

    def comparators(*_: object) -> dict[str, Any]:
        order.append("comparators")
        return {}

    monkeypatch.setattr(reconstruction, "load_frozen_five_minute_comparators", comparators)

    def claim(*_: object) -> str:
        order.append("claim")
        return "a" * 64

    def credentials() -> tuple[str, str]:
        order.append("credentials")
        raise ValueError("credentials absent")

    monkeypatch.setattr(reconstruction, "_claim_source_attempt", claim)
    monkeypatch.setattr(reconstruction, "acquisition_account_environment", lambda: "paper")
    monkeypatch.setattr(reconstruction, "read_acquisition_credentials", credentials)
    monkeypatch.setattr(reconstruction, "_seal_source_attempt", lambda *_: None)
    assert (
        reconstruction.main(
            (
                "--repository",
                str(_REPOSITORY),
                "--data-home",
                str(tmp_path),
                "acquire-source",
            )
        )
        == 64
    )
    assert order == ["comparators", "claim", "credentials"]
    assert "credentials absent" in capsys.readouterr().err


def test_cli_rejects_missing_comparator_evidence_before_claim_or_credentials(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    plan = _plan()
    authority = _authority()
    monkeypatch.setattr(reconstruction, "load_completeness_source_plan", lambda _: plan)
    monkeypatch.setattr(reconstruction, "load_source_authority", lambda *_: authority)
    monkeypatch.setattr(reconstruction, "source_authority_preflight", lambda *_: None)
    monkeypatch.setattr(
        reconstruction,
        "_claim_source_attempt",
        lambda *_: (_ for _ in ()).throw(AssertionError("source attempt claimed")),
    )
    monkeypatch.setattr(
        reconstruction,
        "read_acquisition_credentials",
        lambda: (_ for _ in ()).throw(AssertionError("credentials loaded")),
    )
    assert (
        reconstruction.main(
            (
                "--repository",
                str(_REPOSITORY),
                "--data-home",
                str(tmp_path),
                "acquire-source",
            )
        )
        == 64
    )


def test_cli_checks_authority_before_credentials(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    plan = _plan()
    order: list[str] = []

    def load(_: Path) -> reconstruction.CompletenessSourcePlan:
        order.append("plan")
        return plan

    monkeypatch.setattr(reconstruction, "load_completeness_source_plan", load)

    def blocked(*_: object) -> reconstruction.SourceAuthority:
        order.append("authority")
        raise Program002AcquisitionError("authority blocked")

    monkeypatch.setattr(reconstruction, "load_source_authority", blocked)
    monkeypatch.setattr(
        reconstruction,
        "read_acquisition_credentials",
        lambda: (_ for _ in ()).throw(AssertionError("credentials loaded")),
    )
    assert (
        reconstruction.main(
            (
                "--repository",
                str(_REPOSITORY),
                "--data-home",
                str(tmp_path),
                "acquire-source",
            )
        )
        == 64
    )
    assert order == ["plan", "authority"]
    assert "authority blocked" in capsys.readouterr().err


def test_consumed_authority_rejects_another_data_home_before_credentials(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reconstruction,
        "read_acquisition_credentials",
        lambda: (_ for _ in ()).throw(AssertionError("credentials loaded")),
    )

    assert (
        reconstruction.main(
            (
                "--repository",
                str(_REPOSITORY),
                "--data-home",
                str(tmp_path),
                "acquire-source",
            )
        )
        == 64
    )
    assert "minute-source implementation identity differs" in capsys.readouterr().err
