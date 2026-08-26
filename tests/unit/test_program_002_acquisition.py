from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import Request

import pytest

import systematic_trading_lab.program_002_acquisition as acquisition
from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.catalog import DatasetCatalog
from systematic_trading_lab.config import non_broker_subprocess_environment
from systematic_trading_lab.datasets import DatasetService
from systematic_trading_lab.domain import OHLCVBar, Timeframe
from systematic_trading_lab.fingerprints import canonical_json, canonicalize, fingerprint
from systematic_trading_lab.multi_hour_sector_etf_plan import (
    ACQUISITION_AUTHORITY_RELATIVE_PATH,
    ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH,
    ACQUISITION_SOURCE_PATHS,
    Program002AcquisitionPlan,
    Program002Authority,
)
from systematic_trading_lab.multi_hour_sector_etf_plan import (
    load_program_002_account_proof_plan as load_plan,
)
from systematic_trading_lab.program_002_acquisition import (
    AcquiredSegment,
    HistoricalHttpClient,
    HttpPage,
    Program002AcquisitionError,
    RequestPacer,
    acquire_quote_segments,
    acquire_role_segments,
    acquire_segment,
    acquisition_authority_preflight,
    acquisition_credentials,
    bar_segments,
    derive_quote_costs,
    derive_volume_context_projection,
    load_program_002_quote_cost_artifact,
    load_quote_segments_from_artifacts,
    publish_quote_costs,
    publish_role_dataset_from_artifacts,
    quote_segment_ids,
    quote_segments,
    sample_quote_window,
)
from systematic_trading_lab.storage import StorageLayout

_REPOSITORY = Path(__file__).resolve().parents[2]
_ATTEMPT = "synthetic-attempt-1"


def _v5_plan() -> Program002AcquisitionPlan:
    plan = load_plan(_REPOSITORY)
    payload = {
        "schema_version": "program-002-exposed-acquisition-authority-v5",
        "bindings": {
            "acquisition_control_amendment": {
                "sha256": plan.control_sha256,
                "fingerprint": plan.control_fingerprint,
            },
            "provider_contract_evidence": {
                "sha256": plan.provider_contract_evidence_sha256,
                "fingerprint": plan.provider_contract_evidence_fingerprint,
            },
            "account_isolation_proof": {"sha256": "1" * 64, "fingerprint": "2" * 64},
        },
        "account_isolation": {
            "proof_accepted": True,
            "environment": "paper",
            "credential_key_id_hash": hashlib.sha256(b"dedicated-key").hexdigest(),
        },
        "source_binding": {"source_commit": "4" * 40, "files": []},
    }
    authority = Program002Authority(
        plan.path.parent / ACQUISITION_AUTHORITY_RELATIVE_PATH.name,
        "5" * 64,
        "program-002-exposed-acquisition-2026-08-26-v5",
        payload,
    )
    return replace(plan, authority=authority)


def _page(token: str | None = None) -> HttpPage:
    body = json.dumps(
        {
            "bars": {
                "SPY": [{"t": "2020-07-27T13:30:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]
            },
            "next_page_token": token,
        },
        separators=(",", ":"),
    ).encode()
    return HttpPage(200, body, {"X-Request-ID": "synthetic"})


def _page_at(timestamp: str) -> HttpPage:
    return HttpPage(
        200,
        json.dumps(
            {
                "bars": {"SPY": [{"t": timestamp, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]},
                "next_page_token": None,
            },
            separators=(",", ":"),
        ).encode(),
        {"X-Request-ID": "synthetic"},
    )


def test_exact_bar_query_and_raw_bytes() -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    seen: list[str] = []

    def transport(url: str) -> HttpPage:
        seen.append(url)
        return _page()

    acquired = acquire_segment(segment, transport)
    assert "https://data.alpaca.markets/v2/stocks/bars?" in seen[0]
    assert "feed=sip" in seen[0] and "timeframe=5Min" in seen[0] and "adjustment=all" in seen[0]
    assert "sort=asc" in seen[0] and "limit=10000" in seen[0]
    assert acquired.pages[0].body == _page().body
    assert acquired.normalized_records[0]["symbol"] == "SPY"


def test_pagination_drains_underfilled_pages_and_rejects_repeat_and_ceiling(
    tmp_path: Path,
) -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    assert segment.page_ceiling == 100
    assert quote_segments(load_plan(_REPOSITORY))[0].page_ceiling == 100

    pages = iter([_page(str(index)) for index in range(10)] + [_page()])
    acquired = acquire_segment(segment, lambda _: next(pages), pace=lambda: None)
    assert len(acquired.pages) == 11

    with pytest.raises(Program002AcquisitionError, match="repeated"):
        acquire_segment(segment, lambda _: _page("same"), pace=lambda: None)
    pages = iter([_page(str(index)) for index in range(100)])
    layout = StorageLayout(tmp_path)
    with pytest.raises(Program002AcquisitionError, match="ceiling"):
        acquire_role_segments(
            load_plan(_REPOSITORY),
            "exposed-block-1",
            layout,
            lambda _: next(pages),
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )
    evidence = json.loads(next((tmp_path / "quarantine").glob("*.json")).read_text())
    assert evidence["error"] == "Program 002 page ceiling exceeded"
    assert len(evidence["previous_pages"]) == 100
    terminal = json.loads(
        (tmp_path / "reports" / "program-002" / "acquisition-terminal-attempts.jsonl").read_text()
    )
    assert terminal["error"] == "Program 002 page ceiling exceeded"
    with pytest.raises(Program002AcquisitionError, match="terminal"):
        acquire_segment(segment, lambda _: HttpPage(200, b'{"bars":{}}', {}))


def test_retry_is_bounded_and_injectable() -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    pages = iter([HttpPage(429, b"", {}), _page()])
    waits: list[float] = []
    assert acquire_segment(segment, lambda _: next(pages), retry_wait=waits.append).pages
    assert waits == [1]


def test_http_attempt_evidence_is_ordered_and_quarantined(tmp_path: Path) -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    pages = iter([HttpPage(429, b"retry", {"X-Request-ID": "first"}), _page()])
    acquired = acquire_segment(segment, lambda _: next(pages), retry_wait=lambda _: None)
    attempts = acquired.pages[0].attempts
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert [item["disposition"] for item in attempts] == ["retry", "accepted"]
    assert attempts[0]["captured_body_sha256"] == hashlib.sha256(b"retry").hexdigest()

    layout = StorageLayout(tmp_path)
    later_failure = iter([_page("next"), HttpPage(401, b"denied", {"X-Request-ID": "second"})])
    with pytest.raises(Program002AcquisitionError, match="nonretryable"):
        acquire_segment(segment, lambda _: next(later_failure), quarantine_layout=layout)
    evidence = json.loads(next((tmp_path / "quarantine").glob("*.json")).read_text())
    assert evidence["http_attempts"][0]["status"] == 401
    assert evidence["previous_pages"][0]["http_attempts"][0]["disposition"] == "accepted"


def test_terminal_attempt_journal_records_failed_segment(tmp_path: Path) -> None:
    plan = load_plan(_REPOSITORY)
    with pytest.raises(Program002AcquisitionError, match="malformed provider payload"):
        acquire_role_segments(
            plan,
            "exposed-context-only",
            StorageLayout(tmp_path),
            lambda _: HttpPage(200, b"{", {}),
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )
    journal = tmp_path / "reports" / "program-002" / "acquisition-terminal-attempts.jsonl"
    record = json.loads(journal.read_text(encoding="utf-8"))
    assert record["acquisition_attempt_id"] == _ATTEMPT
    assert record["disposition"] == "failed"
    assert record["http_attempts"][0]["disposition"] == "accepted"


def test_retry_honors_server_delay_and_quarantines_invalid_page(tmp_path: Path) -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    waits: list[float] = []
    pages = iter([HttpPage(429, b"", {"retry-after": "3"}), _page()])
    assert acquire_segment(segment, lambda _: next(pages), retry_wait=waits.append).pages
    assert waits == [3.0]
    waits.clear()
    pages = iter([HttpPage(429, b"", {"Retry-After": "2", "X-RateLimit-Reset": "110"}), _page()])
    assert acquire_segment(
        segment, lambda _: next(pages), retry_wait=waits.append, wall_clock=lambda: 100.0
    ).pages
    assert waits == [10.0]
    retry_layout = StorageLayout(tmp_path / "retry")
    invalid_after_retry = iter(
        [
            HttpPage(429, b"", {}),
            HttpPage(
                200,
                b'{"bars":{"SPY":[{}]},"next_page_token":null}',
                {},
            ),
        ]
    )
    with pytest.raises(Program002AcquisitionError, match="missing fields"):
        acquire_segment(
            segment,
            lambda _: next(invalid_after_retry),
            retry_wait=lambda _: None,
            quarantine_layout=retry_layout,
        )
    evidence = json.loads(next((tmp_path / "retry" / "quarantine").glob("*.json")).read_text())
    assert evidence["http_attempts"][0]["retry_delay_seconds"] == "1"


def test_malformed_transport_records_and_duplicate_keys_fail_closed(tmp_path: Path) -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    malformed = HttpPage(200, b'{"bars":{"SPY":[{"t":"bad"}]}}', {})
    duplicate_key = HttpPage(200, b'{"bars":{},"bars":{}}', {})
    non_finite = HttpPage(
        200,
        b'{"bars":{"SPY":[{"t":"2020-07-27T13:30:00Z","o":NaN,"h":1,"l":1,"c":1,"v":1}]},"next_page_token":null}',
        {},
    )
    with pytest.raises(Program002AcquisitionError, match="missing fields"):
        acquire_segment(segment, lambda _: malformed)
    with pytest.raises(Program002AcquisitionError, match="duplicate key"):
        acquire_segment(segment, lambda _: duplicate_key)
    with pytest.raises(Program002AcquisitionError, match="non-finite"):
        acquire_segment(
            segment,
            lambda _: non_finite,
            quarantine_layout=StorageLayout(tmp_path),
        )
    assert list((tmp_path / "quarantine").glob("*.json"))


def test_extreme_json_numbers_preserve_failure_evidence(tmp_path: Path) -> None:
    plan = load_plan(_REPOSITORY)
    segment = bar_segments(plan, "exposed-context-only")[0]
    decimal_body = (
        b'{"bars":{"SPY":[{"t":"'
        + segment.params["start"].encode()
        + b'","o":1e1000000,"h":1,"l":1,"c":1,"v":1}]},"next_page_token":null}'
    )
    decimal_layout = StorageLayout(tmp_path / "decimal")
    with pytest.raises(Program002AcquisitionError, match="canonical evidence bound"):
        acquire_role_segments(
            plan,
            "exposed-context-only",
            decimal_layout,
            lambda _: HttpPage(200, decimal_body, {}),
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )
    assert list((tmp_path / "decimal" / "quarantine").glob("*.json"))
    terminal = json.loads(
        (
            tmp_path / "decimal" / "reports" / "program-002" / "acquisition-terminal-attempts.jsonl"
        ).read_text()
    )
    assert terminal["disposition"] == "failed"
    assert "canonical evidence bound" in terminal["error"]

    integer_body = (
        b'{"bars":{"SPY":[{"t":"'
        + segment.params["start"].encode()
        + b'","o":1,"h":1,"l":1,"c":1,"v":'
        + (b"9" * 5000)
        + b'}]},"next_page_token":null}'
    )
    integer_layout = StorageLayout(tmp_path / "integer")
    with pytest.raises(Program002AcquisitionError, match="canonical evidence bound"):
        acquire_segment(
            segment,
            lambda _: HttpPage(200, integer_body, {}),
            quarantine_layout=integer_layout,
        )
    assert list((tmp_path / "integer" / "quarantine").glob("*.json"))


def test_transport_extras_are_raw_only_and_outside_bounds_are_quarantined(
    tmp_path: Path,
) -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    start = datetime.fromisoformat(segment.params["start"].replace("Z", "+00:00"))
    in_range_extra = HttpPage(
        200,
        json.dumps(
            {
                "bars": {
                    "SPY": [
                        {
                            "t": segment.params["start"],
                            "o": 1.25,
                            "h": 1.5,
                            "l": 1.0,
                            "c": 1.4,
                            "v": 1,
                        },
                        {
                            "t": (start + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                            "o": 1.25,
                            "h": 1.5,
                            "l": 1.0,
                            "c": 1.4,
                            "v": 1,
                        },
                    ]
                },
                "next_page_token": None,
            }
        ).encode(),
        {},
    )
    acquired = acquire_segment(segment, lambda _: in_range_extra)
    assert len(acquired.raw_records) == 2
    assert len(acquired.normalized_records) == 1

    after_end = datetime.fromisoformat(segment.params["end"].replace("Z", "+00:00"))
    outside_bounds = HttpPage(
        200,
        json.dumps(
            {
                "bars": {
                    "SPY": [
                        {
                            "t": (after_end + timedelta(seconds=1))
                            .isoformat()
                            .replace("+00:00", "Z"),
                            "o": 1.25,
                            "h": 1.5,
                            "l": 1.0,
                            "c": 1.4,
                            "v": 1,
                        }
                    ]
                },
                "next_page_token": None,
            }
        ).encode(),
        {},
    )
    with pytest.raises(Program002AcquisitionError, match="authorized segment"):
        acquire_segment(
            segment, lambda _: outside_bounds, quarantine_layout=StorageLayout(tmp_path)
        )
    bar_evidence = json.loads(next((tmp_path / "quarantine").glob("*.json")).read_text())
    assert bar_evidence["raw_records"][0]["o"] == "1.25"

    quote = quote_segments(load_plan(_REPOSITORY))[0]
    quote_end = datetime.fromisoformat(quote.params["end"].replace("Z", "+00:00"))
    acquisition._require_quote_in_segment({"t": quote.params["end"]}, quote)
    out_of_window = HttpPage(
        200,
        json.dumps(
            {
                "quotes": {
                    "SPY": [
                        {
                            "t": (quote_end + timedelta(seconds=1))
                            .isoformat()
                            .replace("+00:00", "Z"),
                            "bp": 1,
                            "bs": 1,
                            "ap": 1,
                            "as": 1,
                        }
                    ]
                },
                "next_page_token": None,
            }
        ).encode(),
        {},
    )
    with pytest.raises(Program002AcquisitionError, match="authorized window"):
        acquire_segment(quote, lambda _: out_of_window, quarantine_layout=StorageLayout(tmp_path))
    assert list((tmp_path / "quarantine").glob("*.json"))


def test_inclusive_bar_end_is_exact_xnys_final_open() -> None:
    plan = load_plan(_REPOSITORY)
    cases = {
        ("2024-03-08", "2024-03-08"): ("2024-03-08T14:30:00Z", "2024-03-08T20:55:00Z"),
        ("2024-03-11", "2024-03-11"): ("2024-03-11T13:30:00Z", "2024-03-11T19:55:00Z"),
        ("2024-11-29", "2024-11-29"): ("2024-11-29T14:30:00Z", "2024-11-29T17:55:00Z"),
    }
    for (start, end), expected in cases.items():
        segment = acquisition._bar_segment(
            plan, datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
        )
        assert (segment.params["start"], segment.params["end"]) == expected
        acquisition._require_bar_in_segment({"t": expected[1]}, segment)
        with pytest.raises(Program002AcquisitionError, match="outside"):
            acquisition._require_bar_in_segment(
                {
                    "t": (
                        datetime.fromisoformat(expected[1].replace("Z", "+00:00"))
                        + timedelta(minutes=5)
                    )
                    .isoformat()
                    .replace("+00:00", "Z")
                },
                segment,
            )
    with pytest.raises(Program002AcquisitionError, match="no XNYS bars"):
        acquisition._bar_segment(plan, datetime(2024, 7, 4).date(), datetime(2024, 7, 4).date())


def test_every_role_uses_exact_first_and_final_authorized_bar_open() -> None:
    plan = load_plan(_REPOSITORY)
    expected = {
        "exposed-context-only": ("2020-06-26T13:30:00Z", "2020-07-24T19:55:00Z"),
        "exposed-block-1": ("2020-07-27T13:30:00Z", "2022-07-25T19:55:00Z"),
        "exposed-block-2": ("2022-07-26T13:30:00Z", "2024-07-26T19:55:00Z"),
        "exposed-block-3": ("2024-07-29T13:30:00Z", "2026-07-31T19:55:00Z"),
    }
    for role, bounds in expected.items():
        segments = bar_segments(plan, role)
        assert segments[0].params["start"] == bounds[0]
        assert segments[-1].params["end"] == bounds[1]
        end = datetime.fromisoformat(bounds[1].replace("Z", "+00:00"))
        next_session = expected_bar_timestamps(
            end + timedelta(minutes=5), end + timedelta(days=10), Timeframe.FIVE_MINUTES
        )[0]
        with pytest.raises(Program002AcquisitionError, match="outside"):
            acquisition._require_bar_in_segment({"t": next_session}, segments[-1])
    with pytest.raises(Program002AcquisitionError, match="outside"):
        acquisition._require_bar_in_segment(
            {"t": "2027-04-16T13:30:00Z"}, bar_segments(plan, "exposed-block-3")[-1]
        )


def test_protected_dates_and_credential_isolation_are_rejected() -> None:
    plan = load_plan(_REPOSITORY)
    with pytest.raises(Program002AcquisitionError, match="unrecognized"):
        bar_segments(plan, "controlled-a")
    with pytest.raises(Program002AcquisitionError, match="non-acquisition"):
        acquisition_credentials(
            {
                "PROGRAM_002_ACQUISITION_API_KEY_ID": "a",
                "PROGRAM_002_ACQUISITION_API_SECRET_KEY": "b",
                "APCA_API_KEY_ID": "blocked",
            }
        )
    for name in (
        "apca_api_key_id",
        "Alpaca_API_KEY_ID",
        "broker_token",
        "IBKR_API_KEY",
        "paperTrading_api_key",
        "liveTrading_api_key",
    ):
        with pytest.raises(Program002AcquisitionError, match="non-acquisition"):
            acquisition_credentials(
                {
                    "PROGRAM_002_ACQUISITION_API_KEY_ID": "a",
                    "PROGRAM_002_ACQUISITION_API_SECRET_KEY": "b",
                    name: "blocked",
                }
            )


def test_quote_scope_and_import_graph() -> None:
    quotes = quote_segments(load_plan(_REPOSITORY))
    assert len(quotes) == 73 * 9
    assert quotes[0].params["start"].endswith("15:34:25Z")
    assert quotes[0].params["end"].endswith("15:35:30Z")
    source = (_REPOSITORY / "src/systematic_trading_lab/program_002_acquisition.py").read_text()
    assert not any(
        line.startswith(("from .paper", "from .broker", "from .orders"))
        for line in source.splitlines()
    )


def test_quote_sampling_is_strictly_prior_deduplicated_and_covered() -> None:
    start = datetime(2020, 7, 27, 15, 35, tzinfo=UTC)
    records = [
        {
            "symbol": "SPY",
            "t": (start + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z"),
            "bp": 100,
            "bs": 1,
            "ap": 101,
            "as": 1,
        }
        for offset in range(-1, 59)
    ]
    assert len(sample_quote_window(records, "SPY", start)) == 60
    records.insert(1, dict(records[0]))
    assert len(sample_quote_window(records, "SPY", start)) == 60
    with pytest.raises(Program002AcquisitionError, match="57/60"):
        sample_quote_window(records[:1], "SPY", start + timedelta(seconds=6))


def test_volume_context_projection_contains_only_cumulative_volume() -> None:
    from systematic_trading_lab.domain import OHLCVBar

    bars = tuple(
        OHLCVBar.from_record(
            {
                "symbol": "SPY",
                "timestamp": (
                    datetime(2020, 7, 27, 13, 30, tzinfo=UTC) + timedelta(minutes=5 * index)
                )
                .isoformat()
                .replace("+00:00", "Z"),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 7 if index == 0 else 0,
            }
        )
        for index in range(24)
    )
    artifact = derive_volume_context_projection(
        bars, source_dataset_id="dataset", source_dataset_fingerprint="fp"
    )
    assert artifact["rows"] == (
        {
            "session_date": "2020-07-27",
            "symbol": "SPY",
            "cumulative_volume_0930_1130": 7,
            "source_dataset_id": "dataset",
            "source_dataset_fingerprint": "fp",
        },
    )


def test_volume_context_projection_requires_complete_planned_grid() -> None:
    plan = load_plan(_REPOSITORY)
    context = acquisition._role(plan, "exposed-context-only")
    sessions = expected_sessions(
        datetime.fromisoformat(context["inclusive_utc_bar_open_start"].replace("Z", "+00:00")),
        datetime.fromisoformat(context["inclusive_utc_bar_open_end"].replace("Z", "+00:00")),
    )
    bars = tuple(
        OHLCVBar.from_record(
            {
                "symbol": symbol,
                "timestamp": (
                    datetime.combine(session, datetime.min.time(), UTC)
                    + timedelta(hours=13, minutes=30 + 5 * index)
                )
                .isoformat()
                .replace("+00:00", "Z"),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
        )
        for session in sessions
        for symbol in plan.payload["universe"]["symbols"]
        for index in range(24)
    )
    artifact = derive_volume_context_projection(
        bars,
        source_dataset_id="dataset",
        source_dataset_fingerprint="fingerprint",
        plan_sha256=plan.sha256,
    )
    assert len(artifact["rows"]) == 20 * 13
    acquisition._validate_context_projection_rows(artifact, plan, "dataset", "fingerprint")
    malformed = dict(artifact)
    malformed["rows"] = artifact["rows"][:-1]
    with pytest.raises(Program002AcquisitionError, match="coverage"):
        acquisition._validate_context_projection_rows(malformed, plan, "dataset", "fingerprint")


def test_context_projection_publish_load_and_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = load_plan(_REPOSITORY)
    context = acquisition._role(plan, "exposed-context-only")
    sessions = expected_sessions(
        datetime.fromisoformat(context["inclusive_utc_bar_open_start"].replace("Z", "+00:00")),
        datetime.fromisoformat(context["inclusive_utc_bar_open_end"].replace("Z", "+00:00")),
    )
    bars = tuple(
        OHLCVBar.from_record(
            {
                "symbol": symbol,
                "timestamp": (
                    datetime.combine(session, datetime.min.time(), UTC)
                    + timedelta(hours=13, minutes=30 + 5 * index)
                )
                .isoformat()
                .replace("+00:00", "Z"),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": index + 1,
            }
        )
        for session in sessions
        for symbol in plan.payload["universe"]["symbols"]
        for index in range(24)
    )
    manifest = {
        "identity": {"dataset_id": "dataset", "fingerprint": "fingerprint"},
        "program_002": {
            "role": "exposed-context-only",
            "plan_sha256": plan.sha256,
            "acquisition_authority_sha256": plan.authority.sha256,
        },
    }
    monkeypatch.setattr(DatasetCatalog, "get", lambda *_: manifest)
    monkeypatch.setattr(DatasetService, "load_bars", lambda *_: bars)
    layout = StorageLayout(tmp_path)
    path, artifact, created = acquisition.publish_volume_context_projection(plan, layout, "dataset")
    assert created
    assert artifact["acquisition_authority_sha256"] == plan.authority.sha256
    assert canonicalize(
        acquisition.load_volume_context_projection(layout, path.stem, "dataset", plan)
    ) == canonicalize(artifact)
    path.with_suffix(".sha256.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Program002AcquisitionError, match="byte evidence"):
        acquisition.load_volume_context_projection(layout, path.stem, "dataset", plan)
    with pytest.raises(Program002AcquisitionError, match="byte evidence conflicts"):
        acquisition.publish_volume_context_projection(plan, layout, "dataset")
    path.with_suffix(".sha256.json").unlink()
    _, _, recovered = acquisition.publish_volume_context_projection(plan, layout, "dataset")
    assert recovered is False
    assert canonicalize(
        acquisition.load_volume_context_projection(layout, path.stem, "dataset", plan)
    ) == canonicalize(artifact)


def test_final_role_publication_and_correction_parent_excludes_invalid_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = load_plan(_REPOSITORY)
    role = "exposed-context-only"
    target = acquisition._role(plan, role)
    timestamps = expected_bar_timestamps(
        datetime.fromisoformat(target["inclusive_utc_bar_open_start"].replace("Z", "+00:00")),
        datetime.fromisoformat(target["inclusive_utc_bar_open_end"].replace("Z", "+00:00")),
        Timeframe.FIVE_MINUTES,
    )
    records = [
        {
            "symbol": symbol,
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
            "volume": 1,
        }
        for symbol in plan.payload["universe"]["symbols"]
        for timestamp in timestamps
    ]
    layout = StorageLayout(tmp_path)
    segment_id = "a" * 64
    layout.publish(segment_id, {"raw-records.jsonl": '{"source":"synthetic"}\n'})
    segment = {
        "identity": segment_id,
        "content_identity": "content",
        "raw_page_sha256_values": [],
        "request_evidence": [{"retrieval_timestamp": "2020-07-25T00:00:00Z"}],
    }
    published = acquisition._publish_normalized_role(
        plan, role, records, [segment], layout, datetime.now(UTC)
    )
    assert published.created
    assert (
        published.manifest["program_002"]["acquisition_authority_sha256"] == plan.authority.sha256
    )
    assert DatasetService(layout).validate(published.dataset_id)["valid"] is True
    assert acquisition._correction_parent(layout, plan, role, "b" * 64) == published.dataset_id

    valid_manifest = json.loads(
        (layout.dataset(published.dataset_id) / "manifest.json").read_text()
    )
    for identity, mutate in (
        ("c" * 64, lambda value: value["program_002"].update({"plan_sha256": "0" * 64})),
        ("d" * 64, lambda value: value.update({"validation_evidence": {}})),
    ):
        candidate = json.loads(json.dumps(valid_manifest))
        candidate["identity"] = {**candidate["identity"], "dataset_id": identity}
        mutate(candidate)  # type: ignore[no-untyped-call]
        root = layout.dataset(identity)
        root.mkdir(parents=True)
        (root / "manifest.json").write_text(canonical_json(candidate), encoding="utf-8")
    malformed = layout.dataset("e" * 64)
    malformed.mkdir(parents=True)
    (malformed / "manifest.json").write_text("{", encoding="utf-8")
    malformed_sidecar = layout.dataset("f" * 64)
    malformed_sidecar.mkdir(parents=True)
    for name in ("raw.jsonl", "bars.parquet"):
        malformed_sidecar.joinpath(name).write_bytes(
            layout.dataset(published.dataset_id).joinpath(name).read_bytes()
        )
    sidecar_manifest = json.loads(json.dumps(valid_manifest))
    sidecar_manifest["identity"]["dataset_id"] = "f" * 64
    (malformed_sidecar / "manifest.json").write_text(
        canonical_json(sidecar_manifest) + "\n", encoding="utf-8"
    )
    (malformed_sidecar / "manifest.sha256.json").write_text("{", encoding="utf-8")
    assert acquisition._correction_parent(layout, plan, role, "b" * 64) == published.dataset_id

    sidecar_manifest["symbols"] = sidecar_manifest["symbols"][:-1]
    (malformed_sidecar / "manifest.json").write_text(
        canonical_json(sidecar_manifest) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(acquisition, "_manifest_bytes_valid", lambda *_: True)
    monkeypatch.setattr(DatasetService, "validate", lambda *_: {"valid": True})
    assert acquisition._correction_parent(layout, plan, role, "b" * 64) == published.dataset_id


def test_quote_cost_artifact_rejects_incomplete_frozen_scope() -> None:
    plan = load_plan(_REPOSITORY)
    with pytest.raises(Program002AcquisitionError, match="quote segments"):
        derive_quote_costs(plan, ())


def test_provider_contract_preflight_and_reviewed_fee_floor_binding() -> None:
    from systematic_trading_lab.program_002_acquisition import provider_contract_preflight

    plan = load_plan(_REPOSITORY)
    provider_contract_preflight(plan)
    with pytest.raises(Program002AcquisitionError, match="revised acquisition authority"):
        acquisition_authority_preflight(plan)


def test_v5_authority_requires_review_and_account_continuity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _v5_plan()
    with pytest.raises(Program002AcquisitionError, match="review|No such file"):
        acquisition_authority_preflight(plan)

    monkeypatch.setattr(acquisition, "load_program_002_acquisition_authority_review", lambda *_: {})
    monkeypatch.setattr(acquisition, "_repository_source_preflight", lambda *_: None)
    acquisition_authority_preflight(
        plan,
        credential_key_hash=hashlib.sha256(b"dedicated-key").hexdigest(),
        account_environment="paper",
    )
    with pytest.raises(Program002AcquisitionError, match="credential key differs"):
        acquisition_authority_preflight(plan, credential_key_hash="0" * 64)
    with pytest.raises(Program002AcquisitionError, match="environment differs"):
        acquisition_authority_preflight(plan, account_environment="live")


def test_non_broker_subprocess_environment_removes_program_002_credentials() -> None:
    assert non_broker_subprocess_environment(
        {
            "PATH": "/bin",
            "PROGRAM_002_ACQUISITION_ACCOUNT_ENVIRONMENT": "paper",
            "PROGRAM_002_ACQUISITION_API_KEY_ID": "key",
            "PROGRAM_002_ACQUISITION_API_SECRET_KEY": "secret",
            "APCA_API_KEY_ID": "other",
            "GIT_CONFIG_GLOBAL": "other",
        }
    ) == {"PATH": "/bin"}


def test_repository_source_preflight_enforces_reviewed_git_lineage(tmp_path: Path) -> None:
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})

    def git(*arguments: str) -> str:
        return subprocess.run(
            ("git", "-C", str(tmp_path), *arguments),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Program 002 Test")
    git("config", "user.email", "program-002-test@example.invalid")
    proof_path = tmp_path / "config/research/proof.json"
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text("{}\n", encoding="utf-8")
    git("add", proof_path.relative_to(tmp_path).as_posix())
    git("commit", "-m", "proof")
    proof_commit = git("rev-parse", "HEAD")

    source_path = tmp_path / ACQUISITION_SOURCE_PATHS[0]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("source = 1\n", encoding="utf-8")
    git("add", source_path.relative_to(tmp_path).as_posix())
    git("commit", "-m", "implementation")
    source_commit = git("rev-parse", "HEAD")

    authority_path = tmp_path / ACQUISITION_AUTHORITY_RELATIVE_PATH
    authority_bytes = b'{"authority":"test"}\n'
    authority_path.write_bytes(authority_bytes)
    git("add", ACQUISITION_AUTHORITY_RELATIVE_PATH.as_posix())
    git("commit", "-m", "authority")
    authority_commit = git("rev-parse", "HEAD")

    review_path = tmp_path / ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH
    review_bytes = b'{"review":"test"}\n'
    review_path.write_bytes(review_bytes)
    git("add", ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH.as_posix())
    git("commit", "-m", "review")
    review_commit = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", review_commit)

    base = load_plan(_REPOSITORY)
    authority_payload = {
        "source_binding": {
            "source_commit": source_commit,
            "proof_evidence_commit": proof_commit,
        }
    }
    authority = Program002Authority(
        authority_path,
        hashlib.sha256(authority_bytes).hexdigest(),
        "program-002-exposed-acquisition-2026-08-26-v5",
        authority_payload,
    )
    plan = replace(
        base,
        path=tmp_path / "config/research/acquisition-plan.json",
        authority=authority,
    )
    review = {"reviewed_source": {"authority_artifact_commit": authority_commit}}
    acquisition._repository_source_preflight(plan, review)

    (tmp_path / "untracked").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(Program002AcquisitionError, match="clean synchronized"):
        acquisition._repository_source_preflight(plan, review)
    (tmp_path / "untracked").unlink()

    git("update-ref", "refs/remotes/origin/main", authority_commit)
    with pytest.raises(Program002AcquisitionError, match="clean synchronized"):
        acquisition._repository_source_preflight(plan, review)
    git("update-ref", "refs/remotes/origin/main", review_commit)

    wrong_bytes = replace(
        plan,
        authority=Program002Authority(
            authority_path,
            "0" * 64,
            authority.authority_id,
            authority_payload,
        ),
    )
    with pytest.raises(Program002AcquisitionError, match="authority commit bytes"):
        acquisition._repository_source_preflight(wrong_bytes, review)

    source_path.write_text("source = 2\n", encoding="utf-8")
    git("add", source_path.relative_to(tmp_path).as_posix())
    git("commit", "-m", "source drift")
    git("update-ref", "refs/remotes/origin/main", git("rev-parse", "HEAD"))
    with pytest.raises(Program002AcquisitionError, match="source lineage"):
        acquisition._repository_source_preflight(plan, review)


def test_fixed_get_client_and_create_only_cost_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def transport(request: Request) -> HttpPage:
        seen.append(request.full_url)
        return _page()

    plan = load_plan(_REPOSITORY)
    segment = bar_segments(plan, "exposed-block-1")[0]
    with pytest.raises(Program002AcquisitionError, match="revised acquisition authority"):
        HistoricalHttpClient(
            "dedicated-key", "dedicated-secret", "paper", plan, (segment,), transport
        )
    monkeypatch.setattr(acquisition, "acquisition_authority_preflight", lambda *_, **__: None)
    client = HistoricalHttpClient(
        "dedicated-key", "dedicated-secret", "paper", plan, (segment,), transport
    )
    assert client.get(segment.url()).status == 200
    assert seen == [segment.url()]
    with pytest.raises(Program002AcquisitionError, match="authority-bound"):
        client.get("https://data.alpaca.markets/v2/stocks/bars?feed=sip")
    parsed = urlparse(segment.url())
    reversed_query = urlencode(list(reversed(parse_qsl(parsed.query, keep_blank_values=True))))
    assert (
        client.get(f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{reversed_query}").status == 200
    )
    with pytest.raises(Program002AcquisitionError, match="authority-bound"):
        client.get(f"{segment.url()}&extra=blocked")
    with pytest.raises(Program002AcquisitionError, match="authority-bound"):
        client.get(f"{segment.url()}&page_token=one&page_token=two")
    with pytest.raises(Program002AcquisitionError, match="authority-bound"):
        client.get(f"{segment.url()}&page_token=")
    assert client.get(f"{segment.url()}&page_token=next").status == 200
    symbols = {"SPY": {"p50": 1, "p75": 2, "p90": 3, "p95": 4, "p99": 5}}
    artifact = {
        "schema_version": "program-002-quote-cost-artifact-v1",
        "symbols": symbols,
        "quote_artifact_fingerprint": fingerprint(symbols),
    }
    layout = StorageLayout(tmp_path)
    with pytest.raises(Program002AcquisitionError, match="fingerprint|incomplete"):
        publish_quote_costs(
            layout, artifact, load_plan(_REPOSITORY), acquisition_attempt_id=_ATTEMPT
        )


def test_role_segments_resume_from_verified_create_only_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = load_plan(_REPOSITORY)
    segments = bar_segments(plan, "exposed-context-only")
    calls: list[str] = []

    def transport(url: str) -> HttpPage:
        calls.append(url)
        start = dict(parse_qsl(urlparse(url).query))["start"]
        extra = (
            (datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        return HttpPage(
            200,
            json.dumps(
                {
                    "bars": {
                        "SPY": [
                            {"t": start, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
                            {"t": extra, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
                        ]
                    },
                    "next_page_token": None,
                },
                separators=(",", ":"),
            ).encode(),
            {},
        )

    layout = StorageLayout(tmp_path)
    monkeypatch.setattr(acquisition, "_validate_bar_segment_complete", lambda *_: None)
    first = acquire_role_segments(
        plan,
        "exposed-context-only",
        layout,
        transport,
        acquisition_attempt_id=_ATTEMPT,
        pace=lambda: None,
    )
    assert first and calls
    for identity, segment in zip(first, segments, strict=True):
        stored = acquisition._load_segment_artifact(
            layout,
            identity,
            segment,
            "program-002-acquisition-segment-v1",
            role="exposed-context-only",
            plan_sha256=plan.sha256,
            authority_sha256=plan.authority.sha256,
        )
        assert len(stored.raw_records) == 2
        assert len(stored.normalized_records) == 1
    calls.clear()
    assert (
        acquire_role_segments(
            plan,
            "exposed-context-only",
            layout,
            transport,
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )
        == first
    )
    assert not calls
    with pytest.raises(Program002AcquisitionError, match="bar validation"):
        publish_role_dataset_from_artifacts(
            plan,
            "exposed-context-only",
            first,
            layout,
            datetime.now(UTC),
            acquisition_attempt_id=_ATTEMPT,
        )
    journal = tmp_path / "reports" / "program-002" / "acquisition-segments.jsonl"
    journal.unlink()
    assert (
        acquire_role_segments(
            plan,
            "exposed-context-only",
            layout,
            transport,
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )
        == first
    )
    assert journal.exists()
    raw = layout.dataset(first[0]) / "raw-records.jsonl"
    raw.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        Program002AcquisitionError, match="integrity|conflicts|malformed|missing fields"
    ):
        acquire_role_segments(
            plan,
            "exposed-context-only",
            layout,
            transport,
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )


def test_later_acquisition_attempt_creates_child_segment_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = load_plan(_REPOSITORY)
    monkeypatch.setattr(acquisition, "_validate_bar_segment_complete", lambda *_: None)

    def transport(url: str) -> HttpPage:
        return _page_at(dict(parse_qsl(urlparse(url).query))["start"])

    layout = StorageLayout(tmp_path)
    first = acquire_role_segments(
        plan,
        "exposed-context-only",
        layout,
        transport,
        acquisition_attempt_id="synthetic-attempt-1",
        pace=lambda: None,
    )
    valid = json.loads((layout.dataset(first[0]) / "segment.json").read_text())
    assert valid["acquisition_authority_sha256"] == plan.authority.sha256
    stale_alias = layout.datasets / ".stale-segment.tmp"
    stale_alias.mkdir()
    stale_record = {**valid, "parent_segment_id": first[0]}
    stale_record["content_identity"] = fingerprint(
        {key: value for key, value in stale_record.items() if key != "content_identity"}
    )
    (stale_alias / "segment.json").write_text(canonical_json(stale_record) + "\n", encoding="utf-8")
    canonical_path = layout.dataset(first[0]) / "segment.json"
    original_glob = Path.glob

    def ordered_glob(path: Path, pattern: str) -> Iterator[Path]:
        if path == layout.datasets and pattern == "*/segment.json":
            return iter((canonical_path, stale_alias / "segment.json"))
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", ordered_glob)
    assert (
        acquisition._segment_correction_parent(
            layout,
            plan,
            bar_segments(plan, "exposed-context-only")[0],
            "exposed-context-only",
        )
        == first[0]
    )
    monkeypatch.setattr(Path, "glob", original_glob)
    foreign = dict(valid)
    foreign["identity"] = "f" * 64
    foreign["plan_sha256"] = "0" * 64
    foreign["content_identity"] = fingerprint(
        {key: value for key, value in foreign.items() if key != "content_identity"}
    )
    layout.publish("f" * 64, {"segment.json": canonical_json(foreign)})
    malformed = layout.dataset("e" * 64)
    malformed.mkdir(parents=True)
    (malformed / "segment.json").write_text("{", encoding="utf-8")
    tampered = layout.dataset("d" * 64)
    tampered.mkdir(parents=True)
    (tampered / "segment.json").write_text(
        json.dumps({**valid, "identity": "d" * 64}), encoding="utf-8"
    )
    second = acquire_role_segments(
        plan,
        "exposed-context-only",
        layout,
        transport,
        acquisition_attempt_id="synthetic-attempt-2",
        pace=lambda: None,
    )
    assert first != second
    record = json.loads((layout.dataset(second[0]) / "segment.json").read_text())
    assert record["acquisition_attempt_id"] == "synthetic-attempt-2"
    assert record["parent_segment_id"] == first[0]


def test_incomplete_monthly_segment_is_never_persisted(tmp_path: Path) -> None:
    plan = load_plan(_REPOSITORY)
    layout = StorageLayout(tmp_path)
    with pytest.raises(Program002AcquisitionError, match="monthly bar segment"):
        acquire_role_segments(
            plan,
            "exposed-context-only",
            layout,
            lambda url: _page_at(dict(parse_qsl(urlparse(url).query))["start"]),
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )
    assert not list((tmp_path / "datasets").glob("*"))
    evidence = json.loads(next((tmp_path / "quarantine").glob("*.json")).read_text())
    assert evidence["raw_pages"] and evidence["raw_records"]
    assert "monthly bar segment" in evidence["validation_error"]
    assert evidence["acquisition_attempt_id"] == _ATTEMPT
    terminal = json.loads(
        (tmp_path / "reports" / "program-002" / "acquisition-terminal-attempts.jsonl").read_text()
    )
    assert terminal["segment_identity"] == evidence["segment_identity"]
    assert terminal["quarantine_identity"] == fingerprint(evidence)


def test_journal_rejects_missing_artifact(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    journal = tmp_path / "reports" / "program-002" / "acquisition-segments.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"identity": "missing"}) + "\n", encoding="utf-8")
    with pytest.raises(Program002AcquisitionError, match="journal references missing"):
        acquire_role_segments(
            load_plan(_REPOSITORY),
            "exposed-context-only",
            layout,
            lambda _: _page(),
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )


def test_journal_torn_tail_recovery_ignores_stale_repair_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = load_plan(_REPOSITORY)
    monkeypatch.setattr(acquisition, "_validate_bar_segment_complete", lambda *_: None)
    layout = StorageLayout(tmp_path)
    acquire_role_segments(
        plan,
        "exposed-context-only",
        layout,
        lambda url: _page_at(dict(parse_qsl(urlparse(url).query))["start"]),
        acquisition_attempt_id=_ATTEMPT,
        pace=lambda: None,
    )
    segment_journal = tmp_path / "reports" / "program-002" / "acquisition-segments.jsonl"
    segment_journal.write_bytes(segment_journal.read_bytes().rstrip(b"\n"))
    stale = segment_journal.with_name(f".{segment_journal.name}.repair-stale")
    stale.write_text("stale", encoding="utf-8")
    acquisition._validate_segment_journal(layout)
    assert segment_journal.read_bytes().endswith(b"\n") and stale.exists()

    terminal = tmp_path / "reports" / "program-002" / "acquisition-terminal-attempts.jsonl"
    with pytest.raises(Program002AcquisitionError):
        acquire_role_segments(
            plan,
            "exposed-context-only",
            StorageLayout(tmp_path / "terminal"),
            lambda _: HttpPage(200, b"{", {}),
            acquisition_attempt_id=_ATTEMPT,
            pace=lambda: None,
        )
    terminal = (
        tmp_path / "terminal" / "reports" / "program-002" / "acquisition-terminal-attempts.jsonl"
    )
    terminal.write_bytes(terminal.read_bytes().rstrip(b"\n"))
    acquisition._validate_terminal_attempt_journal(StorageLayout(tmp_path / "terminal"))
    assert terminal.read_bytes().endswith(b"\n")


def test_retry_transport_errors_http_date_and_server_pacing() -> None:
    segment = bar_segments(load_plan(_REPOSITORY), "exposed-block-1")[0]
    waits: list[float] = []
    pages: list[HttpPage | BaseException] = [
        HTTPError("https://data.alpaca.markets", 503, "unavailable", Message(), None),
        URLError("down"),
        TimeoutError(),
        ConnectionResetError(),
        _page(),
    ]

    def transport(_: str) -> HttpPage:
        value = pages.pop(0)
        if isinstance(value, BaseException):
            raise value
        assert isinstance(value, HttpPage)
        return value

    assert acquire_segment(segment, transport, retry_wait=waits.append).pages
    assert waits == [1.0, 2.0, 4.0, 8.0]
    waits.clear()
    retry_at = "Thu, 01 Jan 1970 00:01:50 GMT"
    retry_pages = [HttpPage(429, b"", {"Retry-After": retry_at}), _page()]
    assert acquire_segment(
        segment,
        lambda _: retry_pages.pop(0),
        retry_wait=waits.append,
        wall_clock=lambda: 100.0,
    ).pages
    assert waits == [10.0]
    with pytest.raises(Program002AcquisitionError, match="nonretryable"):
        acquire_segment(segment, lambda _: HttpPage(401, b"", {}), retry_wait=waits.append)
    slept: list[float] = []
    pacer = RequestPacer(monotonic=lambda: 0.0, sleep=slept.append)
    pacer()
    pacer.update_server_limit({"X-RateLimit-Limit": "60"})
    pacer()
    assert slept == [1.0]
    pacer = RequestPacer(monotonic=lambda: 0.0, sleep=slept.append)
    pacer()
    pacer.update_server_limit({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "2"}, lambda: 0.0)
    pacer()
    assert slept[-1] == 2.0


def test_quote_derivation_reads_verified_persisted_window_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = load_plan(_REPOSITORY)
    segment = quote_segments(plan)[0]
    monkeypatch.setattr(acquisition, "quote_segments", lambda _: (segment,))
    start = datetime.fromisoformat(segment.params["start"].replace("Z", "+00:00")) + timedelta(
        seconds=5
    )
    quotes = {
        symbol: [
            {
                "t": (start + timedelta(seconds=second)).isoformat().replace("+00:00", "Z"),
                "bp": 100,
                "bs": 1,
                "ap": 101,
                "as": 1,
            }
            for second in range(-1, 59)
        ]
        for symbol in plan.payload["universe"]["symbols"]
    }
    page = HttpPage(200, json.dumps({"quotes": quotes, "next_page_token": None}).encode(), {})
    layout = StorageLayout(tmp_path)
    identifiers = acquire_quote_segments(
        plan, layout, lambda _: page, acquisition_attempt_id=_ATTEMPT, pace=lambda: None
    )
    assert identifiers == quote_segment_ids(plan, _ATTEMPT)
    loaded = load_quote_segments_from_artifacts(
        plan, layout, identifiers, acquisition_attempt_id=_ATTEMPT
    )
    artifact = derive_quote_costs(plan, loaded)
    assert artifact["acquisition_authority_sha256"] == plan.authority.sha256
    assert set(artifact["symbols"]) == set(plan.payload["universe"]["symbols"])
    assert artifact["scenario_metadata"]["Stress_A"]["execution_delay_bars"] == 2
    assert artifact["scenario_metadata"]["Stress_B"]["execution_delay_bars"] == 3
    segment_path = layout.dataset(identifiers[0]) / "segment.json"
    original_segment = json.loads(segment_path.read_text())
    forged_segment = {**original_segment, "plan_sha256": "0" * 64}
    forged_segment["content_identity"] = fingerprint(
        {name: value for name, value in forged_segment.items() if name != "content_identity"}
    )
    segment_path.write_text(canonical_json(forged_segment) + "\n", encoding="utf-8")
    with pytest.raises(Program002AcquisitionError, match="stored segment artifact conflicts"):
        load_quote_segments_from_artifacts(
            plan, layout, identifiers, acquisition_attempt_id=_ATTEMPT
        )
    segment_path.write_text(canonical_json(original_segment) + "\n", encoding="utf-8")
    (layout.dataset(identifiers[0]) / "raw-page-0001.json").write_bytes(b"tampered")
    with pytest.raises(Program002AcquisitionError, match="raw page bytes"):
        load_quote_segments_from_artifacts(
            plan, layout, identifiers, acquisition_attempt_id=_ATTEMPT
        )


def test_all_quote_windows_persist_and_load_from_real_artifacts(tmp_path: Path) -> None:
    plan = load_plan(_REPOSITORY)
    layout = StorageLayout(tmp_path)

    def transport(url: str) -> HttpPage:
        start = datetime.fromisoformat(
            dict(parse_qsl(urlparse(url).query))["start"].replace("Z", "+00:00")
        )
        quotes = {
            symbol: [
                {
                    "t": (start + timedelta(seconds=second + 4)).isoformat().replace("+00:00", "Z"),
                    "bp": 100,
                    "bs": 1,
                    "ap": 101,
                    "as": 1,
                }
                for second in range(-1, 59)
            ]
            for symbol in plan.payload["universe"]["symbols"]
        }
        return HttpPage(200, json.dumps({"quotes": quotes, "next_page_token": None}).encode(), {})

    identifiers = acquire_quote_segments(
        plan, layout, transport, acquisition_attempt_id=_ATTEMPT, pace=lambda: None
    )
    assert identifiers == quote_segment_ids(plan, _ATTEMPT)
    assert len(identifiers) == 657
    assert all((layout.dataset(identity) / "segment.json").is_file() for identity in identifiers)
    loaded = load_quote_segments_from_artifacts(
        plan, layout, identifiers, acquisition_attempt_id=_ATTEMPT
    )
    artifact = derive_quote_costs(plan, loaded)
    assert len(artifact["windows"]) == 657


def test_malformed_quotes_are_counted_and_excluded() -> None:
    start = datetime(2020, 7, 27, 15, 35, tzinfo=UTC)
    records: list[dict[str, object]] = [
        {
            "symbol": "SPY",
            "t": (start + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z"),
            "bp": 100,
            "bs": 1,
            "ap": 101,
            "as": 1,
        }
        for offset in range(-1, 59)
    ]
    records.append(
        {
            "symbol": "SPY",
            "t": (start + timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
            "bp": "bad",
            "bs": 1,
            "ap": 101,
            "as": 1,
        }
    )
    observations, evidence = acquisition._quote_window_evidence(records, "SPY", start)
    assert len(observations) == 60
    assert evidence["malformed"] == 1


def test_malformed_newer_quote_state_prevents_old_quote_backfill() -> None:
    start = datetime(2020, 7, 27, 15, 35, tzinfo=UTC)
    records: list[dict[str, object]] = [
        {
            "symbol": "SPY",
            "t": (start - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "bp": 100,
            "bs": 1,
            "ap": 101,
            "as": 1,
        },
        {
            "symbol": "SPY",
            "t": (start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "bp": "bad",
            "bs": 1,
            "ap": 101,
            "as": 1,
        },
        {
            "symbol": "SPY",
            "t": (start + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
            "bp": 100,
            "bs": 1,
            "ap": 101,
            "as": 1,
        },
    ] + [
        {
            "symbol": "SPY",
            "t": (start + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z"),
            "bp": 100,
            "bs": 1,
            "ap": 101,
            "as": 1,
        }
        for offset in range(3, 61)
    ]
    observations, evidence = acquisition._quote_window_evidence(records, "SPY", start)
    assert len(observations) == 59
    assert evidence["malformed"] == 1


def test_full_quote_artifact_publish_load_and_tamper_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = load_plan(_REPOSITORY)
    segments = quote_segments(plan)
    acquired_segments = tuple(
        AcquiredSegment(
            segment,
            (),
            tuple(
                {
                    "symbol": symbol,
                    "t": (
                        datetime.fromisoformat(segment.params["start"].replace("Z", "+00:00"))
                        + timedelta(seconds=second + 5)
                    )
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "bp": 100,
                    "bs": 1,
                    "ap": 101,
                    "as": 1,
                }
                for symbol in plan.payload["universe"]["symbols"]
                for second in range(-1, 59)
            ),
            (),
        )
        for segment in segments
    )
    monkeypatch.setattr(
        acquisition, "load_quote_segments_from_artifacts", lambda *_, **__: acquired_segments
    )
    artifact = derive_quote_costs(plan, acquired_segments)
    layout = StorageLayout(tmp_path)
    path, created = publish_quote_costs(layout, artifact, plan, acquisition_attempt_id=_ATTEMPT)
    assert created and load_program_002_quote_cost_artifact(
        layout, path.stem, plan, acquisition_attempt_id=_ATTEMPT
    )
    path.with_suffix(".sha256.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Program002AcquisitionError, match="byte evidence differs"):
        load_program_002_quote_cost_artifact(
            layout, path.stem, plan, acquisition_attempt_id=_ATTEMPT
        )
    with pytest.raises(Program002AcquisitionError, match="byte evidence conflicts"):
        publish_quote_costs(layout, artifact, plan, acquisition_attempt_id=_ATTEMPT)
    path.with_suffix(".sha256.json").unlink()
    _, recovered = publish_quote_costs(layout, artifact, plan, acquisition_attempt_id=_ATTEMPT)
    assert recovered is False
    tampered = dict(artifact)
    windows = [dict(item) for item in artifact["windows"]]
    windows[0]["sampled_observation_fingerprint"] = "0" * 64
    tampered["windows"] = windows
    tampered["quote_artifact_fingerprint"] = fingerprint(
        {name: item for name, item in tampered.items() if name != "quote_artifact_fingerprint"}
    )
    with pytest.raises(Program002AcquisitionError):
        publish_quote_costs(layout, tampered, plan, acquisition_attempt_id=_ATTEMPT)

    for mutate in (
        lambda value: value["windows"][0].update({"raw_page_sha256_values": ["0" * 64]}),
        lambda value: value["windows"][0]["dispositions"]["SPY"].update({"missing": 1}),
        lambda value: value["window_distributions"]["spread"]["SPY"].update(
            {"p99": Decimal("999")}
        ),
        lambda value: value["regulatory_fee_model"].update({"source_cost_model_id": "forged"}),
        lambda value: value["scenario_metadata"]["Normal"].update({"execution_delay_bars": 9}),
    ):
        forged = json.loads(json.dumps(canonicalize(artifact)))
        forged = acquisition._decode_quote_artifact_decimals(forged)
        mutate(forged)  # type: ignore[no-untyped-call]
        forged["quote_artifact_fingerprint"] = fingerprint(
            {name: item for name, item in forged.items() if name != "quote_artifact_fingerprint"}
        )
        with pytest.raises(Program002AcquisitionError):
            publish_quote_costs(layout, forged, plan, acquisition_attempt_id=_ATTEMPT)
