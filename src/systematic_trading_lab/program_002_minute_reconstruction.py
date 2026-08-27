"""Terminally revoked Program 002 minute-source reconstruction boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, urlparse
from urllib.request import Request

from .calendar import expected_bar_timestamps
from .config import non_broker_subprocess_environment
from .domain import Timeframe
from .fingerprints import canonical_json, canonicalize, fingerprint
from .multi_hour_sector_etf_plan import (
    ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH,
    ACCOUNT_ISOLATION_PROOF_REVIEW_RELATIVE_PATH,
    ACQUISITION_SOURCE_PATHS,
    PROGRAM_ID,
    PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_FINGERPRINT,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_FINGERPRINT,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_SHA256,
    REVIEWED_ACCOUNT_ISOLATION_PROOF_SHA256,
    REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT,
    REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
)
from .program_002_acquisition import (
    AcquiredSegment,
    HttpPage,
    Program002AcquisitionError,
    RawPage,
    RequestPacer,
    RequestSegment,
    acquire_segment,
)
from .program_002_credentials import (
    acquisition_account_environment,
    credential_key_id_hash,
    read_acquisition_credentials,
)
from .storage import StorageLayout

_PLAN_RELATIVE_PATH = Path(
    "config/research/program-002-acquisition-completeness-data-source-plan-v1.json"
)
_PLAN_REVIEW_RELATIVE_PATH = Path(
    "config/research/"
    "program-002-acquisition-completeness-data-source-plan-independent-review-v1.json"
)
_IMPLEMENTATION_REVIEW_RELATIVE_PATH = Path(
    "config/research/program-002-minute-reconstruction-implementation-independent-review-v1.json"
)
_SOURCE_AUTHORITY_RELATIVE_PATH = Path(
    "config/research/program-002-minute-reconstruction-source-authority-v1.json"
)
_SOURCE_AUTHORITY_REVIEW_RELATIVE_PATH = Path(
    "config/research/program-002-minute-reconstruction-source-authority-independent-review-v1.json"
)
_PLAN_SHA256 = "c45a5f749a120d600973753804533f7b7a9f352b0335d89a32bde990f3227735"
_PLAN_FINGERPRINT = "07edec3a871a68f9c0a9d64842d6b8e668bf1c2af77cd885b12c61e27d27e8f8"
_PLAN_REVIEW_SHA256 = "27470f80dcd89c05c614cc2ab81206e726263bf00afe0c21b5faa5dfb4f75bb0"
_PLAN_REVIEW_FINGERPRINT = "3dfad1b705d07d47915b19048d02e8ef352afc290e40ad5b4347485a08f710a5"
_SOURCE_AUTHORIZATION_SHA256 = "d58f06bb3eabb8bae6a7a242d8a5e44ba3921fbb640e06ff81d6317d474c77d5"
_BARS = "https://data.alpaca.markets/v2/stocks/bars"
_SOURCE_SEGMENT_SCHEMA = "program-002-minute-source-segment-v1"
_SOURCE_PROOF_SCHEMA = "program-002-minute-reconstruction-source-proof-v1"
_SOURCE_PROOF_NAME = "program-002-minute-reconstruction-source-proof-v1.json"
_AUTHORITY_KEYS = frozenset(
    {
        "market_data_acquisition",
        "strategy_implementation",
        "strategy_execution",
        "research_qualification",
        "controlled_evaluation",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
    }
)
_SOURCE_CONTROL_KEYS = frozenset(
    {
        "raw_source_acquisition",
        "source_proof_publication",
        "canonical_admission",
        "remaining_bar_acquisition",
        "quote_acquisition",
        "cost_calibration",
    }
)
_SOURCE_PATH = "src/systematic_trading_lab/program_002_minute_reconstruction.py"
SOURCE_PATHS = (*ACQUISITION_SOURCE_PATHS, _SOURCE_PATH)


@dataclass(frozen=True)
class CompletenessSourcePlan:
    repository: Path
    path: Path
    sha256: str
    fingerprint: str
    payload: Mapping[str, Any]
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    review: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "review", MappingProxyType(dict(self.review)))


@dataclass(frozen=True)
class SourceAuthority:
    path: Path
    sha256: str
    fingerprint: str
    payload: Mapping[str, Any]
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    review: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "review", MappingProxyType(dict(self.review)))


@dataclass(frozen=True)
class MinuteBar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: int
    page_sha256: str


class MinuteSourceHttpClient:
    """Fixed-origin GET client restricted to the four reviewed source chains."""

    def __init__(
        self,
        api_key: str,
        secret: str,
        environment: str,
        plan: CompletenessSourcePlan,
        authority: SourceAuthority,
        segments: Sequence[RequestSegment],
        transport: Callable[[Request], HttpPage] | None = None,
    ) -> None:
        source_authority_preflight(
            plan,
            authority,
            credential_key_hash=credential_key_id_hash(api_key),
            account_environment=environment,
        )
        if not api_key or not secret:
            raise ValueError("Program 002 acquisition credentials are required")
        supplied = tuple(segments)
        expected = minute_source_segments(plan)
        if supplied != expected:
            raise Program002AcquisitionError("minute-source client scope differs")
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret}
        self._transport = transport or _urlopen_page
        self._requests = {
            _request_identity(item.url(), allow_page_token=False) for item in supplied
        }

    def get(self, url: str) -> HttpPage:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "data.alpaca.markets"
            or parsed.path != "/v2/stocks/bars"
            or _request_identity(url, allow_page_token=True) not in self._requests
        ):
            raise Program002AcquisitionError("minute-source request differs from reviewed scope")
        return self._transport(Request(url, headers=self._headers, method="GET"))


def load_completeness_source_plan(repository: Path) -> CompletenessSourcePlan:
    repository = repository.resolve()
    path = repository / _PLAN_RELATIVE_PATH
    review_path = repository / _PLAN_REVIEW_RELATIVE_PATH
    raw = path.read_bytes()
    review_raw = review_path.read_bytes()
    _require_sha256(raw, _PLAN_SHA256, "completeness-source plan")
    _require_sha256(review_raw, _PLAN_REVIEW_SHA256, "completeness-source plan review")
    payload = _load_unique_json(raw, "completeness-source plan")
    review = _load_unique_json(review_raw, "completeness-source plan review")
    unsigned = dict(payload)
    plan_fingerprint = unsigned.pop("plan_fingerprint", None)
    review_unsigned = dict(review)
    review_fingerprint = review_unsigned.pop("review_fingerprint", None)
    if (
        payload.get("schema_version") != "program-002-acquisition-completeness-data-source-plan-v1"
        or payload.get("plan_id") != "program-002-alpaca-minute-reconstruction-2026-08-26-v1"
        or payload.get("program_id") != PROGRAM_ID
        or plan_fingerprint != _PLAN_FINGERPRINT
        or fingerprint(unsigned) != _PLAN_FINGERPRINT
        or review.get("schema_version")
        != "program-002-acquisition-completeness-data-source-plan-independent-review-v1"
        or review.get("status") != "passed-prospective-plan-before-implementation-or-acquisition"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("reviewed_plan")
        != {
            "path": _PLAN_RELATIVE_PATH.as_posix(),
            "sha256": _PLAN_SHA256,
            "fingerprint": _PLAN_FINGERPRINT,
        }
        or review_fingerprint != _PLAN_REVIEW_FINGERPRINT
        or fingerprint(review_unsigned) != _PLAN_REVIEW_FINGERPRINT
    ):
        raise Program002AcquisitionError("completeness-source plan or review differs")
    _require_false_authority(payload.get("authority"), "completeness-source plan")
    _require_false_authority(review.get("authority"), "completeness-source plan review")
    if any(_mapping(payload.get("launch_control"), "source-plan launch control").values()):
        raise Program002AcquisitionError("completeness-source plan unexpectedly grants authority")
    for binding in _mapping(payload.get("immutable_bindings"), "immutable bindings").values():
        item = _mapping(binding, "immutable binding")
        relative = item.get("path")
        expected_sha = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_sha, str):
            raise Program002AcquisitionError("completeness-source binding differs")
        _require_sha256(
            (repository / relative).read_bytes(), expected_sha, f"completeness binding {relative}"
        )
    plan = CompletenessSourcePlan(
        repository,
        path,
        _PLAN_SHA256,
        _PLAN_FINGERPRINT,
        payload,
        review_path,
        _PLAN_REVIEW_SHA256,
        _PLAN_REVIEW_FINGERPRINT,
        review,
    )
    _verify_frozen_source_scope(plan)
    return plan


def minute_source_segments(plan: CompletenessSourcePlan) -> tuple[RequestSegment, ...]:
    selected = _mapping(plan.payload.get("selected_data_source"), "selected data source")
    endpoint = str(selected.get("endpoint", ""))
    if not endpoint.startswith("GET "):
        raise Program002AcquisitionError("minute-source endpoint differs")
    return tuple(
        RequestSegment(
            "bars",
            endpoint.removeprefix("GET "),
            {
                "symbols": "MDY",
                "start": _text(item, "start"),
                "end": _text(item, "end"),
                "feed": "sip",
                "limit": "10000",
                "sort": "asc",
                "timeframe": "1Min",
                "adjustment": "all",
            },
            100,
        )
        for item in _mapping_sequence(
            plan.payload.get("exact_one_minute_request_segments"), "minute request segments"
        )
    )


def load_source_authority(repository: Path, plan: CompletenessSourcePlan) -> SourceAuthority:
    repository = repository.resolve()
    path = repository / _SOURCE_AUTHORITY_RELATIVE_PATH
    review_path = repository / _SOURCE_AUTHORITY_REVIEW_RELATIVE_PATH
    try:
        raw = path.read_bytes()
        review_raw = review_path.read_bytes()
    except OSError as error:
        raise Program002AcquisitionError(
            "reviewed one-use minute-source authority is absent"
        ) from error
    payload = _load_unique_json(raw, "minute-source authority")
    review = _load_unique_json(review_raw, "minute-source authority review")
    unsigned = dict(payload)
    authority_fingerprint = unsigned.pop("authority_fingerprint", None)
    review_unsigned = dict(review)
    review_fingerprint = review_unsigned.pop("review_fingerprint", None)
    sha256 = hashlib.sha256(raw).hexdigest()
    review_sha256 = hashlib.sha256(review_raw).hexdigest()
    if (
        payload.get("schema_version") != "program-002-minute-reconstruction-source-authority-v1"
        or payload.get("authority_id") != "program-002-minute-reconstruction-source-2026-08-26-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "active-one-use-before-source-proof"
        or payload.get("source_authorization")
        != {
            "kind": "user-supplied-completeness-source-implementation-authorization",
            "sha256": _SOURCE_AUTHORIZATION_SHA256,
        }
        or not _is_sha256(authority_fingerprint)
        or authority_fingerprint != fingerprint(unsigned)
        or review.get("schema_version")
        != "program-002-minute-reconstruction-source-authority-independent-review-v1"
        or review.get("status") != "passed-before-minute-source-request"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("reviewed_authority")
        != {
            "path": _SOURCE_AUTHORITY_RELATIVE_PATH.as_posix(),
            "sha256": sha256,
            "fingerprint": authority_fingerprint,
        }
        or not _is_sha256(review_fingerprint)
        or review_fingerprint != fingerprint(review_unsigned)
    ):
        raise Program002AcquisitionError("minute-source authority or review differs")
    _verify_source_authority_bindings(repository, plan, payload)
    source = _mapping(payload.get("source_binding"), "minute-source binding")
    reviewed_source = _mapping(review.get("reviewed_source"), "reviewed minute-source")
    if (
        reviewed_source.get("source_commit") != source.get("source_commit")
        or reviewed_source.get("files") != source.get("files")
        or not _is_commit(reviewed_source.get("authority_artifact_commit"))
    ):
        raise Program002AcquisitionError("reviewed minute-source identity differs")
    _require_false_authority(review.get("authority"), "minute-source authority review")
    return SourceAuthority(
        path,
        sha256,
        str(authority_fingerprint),
        payload,
        review_path,
        review_sha256,
        str(review_fingerprint),
        review,
    )


def source_authority_preflight(
    plan: CompletenessSourcePlan,
    authority: SourceAuthority,
    *,
    credential_key_hash: str | None = None,
    account_environment: str | None = None,
) -> None:
    account = _mapping(authority.payload.get("account_isolation"), "source account binding")
    if credential_key_hash is not None and credential_key_hash != account.get(
        "credential_key_id_hash"
    ):
        raise Program002AcquisitionError("minute-source credential differs from account proof")
    if account_environment is not None and account_environment != account.get("environment"):
        raise Program002AcquisitionError("minute-source environment differs from account proof")
    _repository_source_preflight(plan, authority)


def acquire_minute_sources(
    plan: CompletenessSourcePlan,
    authority: SourceAuthority,
    layout: StorageLayout,
    transport: Callable[[str], HttpPage],
    *,
    claim_fingerprint: str,
    pace: Callable[[], None] | None = None,
) -> tuple[str, ...]:
    """Acquire or reload each exact source chain; a terminal failure cannot retry."""
    attempt_id = _text(authority.payload, "acquisition_attempt_id")
    _source_attempt_preflight(layout, attempt_id)
    _start_source_attempt(layout, plan, authority, claim_fingerprint)
    _validate_source_segment_journal(layout)
    completed: list[str] = []
    shared_pace = RequestPacer() if pace is None else pace
    for segment in minute_source_segments(plan):
        acquired: AcquiredSegment | None = None
        identity = _source_segment_identity(plan, authority, segment, attempt_id)
        if (layout.dataset(identity) / "segment.json").exists():
            _load_source_segment(layout, identity, plan, authority, segment, attempt_id)
            completed.append(identity)
            continue
        try:
            acquired = acquire_segment(
                segment,
                transport,
                pace=shared_pace,
                quarantine_layout=layout,
                request_attempt_limit=1,
            )
            _validate_source_segment(segment, acquired)
        except Program002AcquisitionError as error:
            quarantine_identity: str | None
            if acquired is not None:
                quarantine_identity = _quarantine_source_segment(
                    layout, segment, acquired, error, attempt_id, identity
                )
            else:
                linked_quarantine = getattr(error, "quarantine_identity", None)
                quarantine_identity = (
                    linked_quarantine if isinstance(linked_quarantine, str) else None
                )
            _append_source_failure(
                layout, attempt_id, segment, error, identity, quarantine_identity
            )
            raise
        record = _source_segment_record(plan, authority, segment, acquired, attempt_id, identity)
        files: dict[str, str | bytes] = {
            "segment.json": canonical_json(record) + "\n",
            "raw-records.jsonl": "".join(
                canonical_json(item) + "\n" for item in acquired.raw_records
            ),
            **{
                f"raw-page-{index:04d}.json": page.body
                for index, page in enumerate(acquired.pages, 1)
            },
        }
        if not layout.publish(identity, files):
            stored = _load_source_segment(layout, identity, plan, authority, segment, attempt_id)
            if (
                _source_segment_record(plan, authority, segment, stored, attempt_id, identity)
                != record
            ):
                raise Program002AcquisitionError("stored minute-source segment conflicts")
        _append_source_segment_journal(layout, record)
        completed.append(identity)
    return tuple(completed)


def derive_minute_reconstruction(
    plan: CompletenessSourcePlan,
    sources: Sequence[AcquiredSegment],
    comparators: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    segments = minute_source_segments(plan)
    if len(sources) != len(segments) or any(
        acquired.segment != expected for acquired, expected in zip(sources, segments, strict=True)
    ):
        raise Program002AcquisitionError("minute-source segment set differs")
    aggregates: dict[str, Mapping[str, Any]] = {}
    ledgers: dict[str, Mapping[str, Any]] = {}
    source_row_count = 0
    for acquired in sources:
        rows = _validate_source_segment(acquired.segment, acquired)
        source_row_count += len(rows)
        for aggregate, source_ledger in _aggregate_source_segment(acquired.segment, rows):
            coordinate = f"MDY@{aggregate['timestamp']}"
            if coordinate in aggregates:
                raise Program002AcquisitionError("duplicate derived five-minute coordinate")
            aggregates[coordinate] = aggregate
            ledgers[coordinate] = source_ledger
    targets = set(_string_sequence(plan.payload.get("exact_derived_coordinates"), "targets"))
    expected = _expected_five_minute_coordinates(segments)
    expected_controls = expected - targets
    if set(aggregates) != expected or set(comparators) != expected_controls:
        raise Program002AcquisitionError("five-minute comparator coordinate set differs")
    comparison: list[Mapping[str, Any]] = []
    for coordinate in sorted(expected_controls):
        aggregate = aggregates[coordinate]
        comparator = comparators[coordinate]
        aggregate_fields = {
            "open": _decimal(aggregate.get("open"), "derived open"),
            "high": _decimal(aggregate.get("high"), "derived high"),
            "low": _decimal(aggregate.get("low"), "derived low"),
            "close": _decimal(aggregate.get("close"), "derived close"),
            "volume": _integer(aggregate.get("volume"), "derived volume"),
            "trade_count": _integer(aggregate.get("trade_count"), "derived trade count"),
        }
        comparator_fields = {
            "open": _decimal(comparator.get("open"), "comparator open"),
            "high": _decimal(comparator.get("high"), "comparator high"),
            "low": _decimal(comparator.get("low"), "comparator low"),
            "close": _decimal(comparator.get("close"), "comparator close"),
            "volume": _integer(comparator.get("volume"), "comparator volume"),
            "trade_count": _integer(comparator.get("trade_count"), "comparator trade count"),
        }
        if aggregate_fields != comparator_fields:
            raise Program002AcquisitionError(
                f"minute reconstruction differs at frozen comparator {coordinate}"
            )
        comparison.append({"coordinate": coordinate, "disposition": "exact-match"})
    derived = [
        {
            **aggregates[coordinate],
            "symbol": "MDY",
            "origin": "provider-derived-from-1m",
        }
        for coordinate in sorted(targets)
    ]
    derivation_ledger = [
        {
            **ledgers[coordinate],
            "coordinate": coordinate,
            "disposition": (
                "authorized-derived-coordinate" if coordinate in targets else "exact-control-match"
            ),
        }
        for coordinate in sorted(expected)
    ]
    counts = _mapping(plan.payload.get("expected_counts"), "expected source counts")
    if (
        len(aggregates) != counts.get("affected_session_expected_five_minute_coordinates")
        or len(comparison)
        != counts.get("affected_session_frozen_provider_observed_five_minute_rows")
        or len(derived) != counts.get("affected_session_exact_provider_derived_one_minute_rows")
        or source_row_count < counts.get("one_minute_source_row_count_minimum", -1)
        or source_row_count > counts.get("one_minute_source_row_count_maximum", -1)
    ):
        raise Program002AcquisitionError("minute reconstruction counts differ")
    artifact = canonicalize(
        {
            "algorithm_version": "program-002-provider-minute-reconstruction-v1",
            "plan_sha256": plan.sha256,
            "source_row_count": source_row_count,
            "aggregate_count": len(aggregates),
            "control_match_count": len(comparison),
            "derived_count": len(derived),
            "comparison": comparison,
            "derived_records": derived,
            "derivation_ledger": derivation_ledger,
            "derivation_ledger_fingerprint": fingerprint(tuple(derivation_ledger)),
            "derived_records_fingerprint": fingerprint(tuple(derived)),
        }
    )
    assert isinstance(artifact, dict)
    return artifact


def load_frozen_five_minute_comparators(
    plan: CompletenessSourcePlan, layout: StorageLayout
) -> dict[str, Mapping[str, Any]]:
    lineage = _mapping(plan.payload.get("frozen_runtime_lineage"), "frozen runtime lineage")
    identity = _text(lineage, "failed_february_quarantine_identity")
    path = layout.quarantine / f"{identity}.json"
    raw = path.read_bytes()
    _require_sha256(
        raw,
        _text(lineage, "failed_february_quarantine_sha256"),
        "frozen February quarantine",
    )
    evidence = _provider_json(raw)
    if (
        evidence.get("acquisition_attempt_id") != lineage.get("acquisition_attempt_id")
        or evidence.get("segment_identity") != lineage.get("failed_february_segment_identity")
        or evidence.get("validation_error") != "monthly bar segment validation failed"
    ):
        raise Program002AcquisitionError("frozen February evidence identity differs")
    records = evidence.get("raw_records")
    if not isinstance(records, list):
        raise Program002AcquisitionError("frozen February records are absent")
    expected = _expected_five_minute_coordinates(minute_source_segments(plan))
    output: dict[str, Mapping[str, Any]] = {}
    for raw_record in records:
        if not isinstance(raw_record, Mapping) or raw_record.get("symbol") != "MDY":
            continue
        try:
            timestamp = _utc(raw_record.get("t"))
        except Program002AcquisitionError:
            continue
        coordinate = f"MDY@{_iso(timestamp)}"
        if coordinate not in expected:
            continue
        if coordinate in output:
            raise Program002AcquisitionError("duplicate frozen comparator coordinate")
        bar = _five_minute_comparator(raw_record)
        output[coordinate] = bar
    targets = set(_string_sequence(plan.payload.get("exact_derived_coordinates"), "targets"))
    if set(output) != expected - targets:
        raise Program002AcquisitionError("frozen comparator coordinate set differs")
    return output


def publish_source_proof(
    plan: CompletenessSourcePlan,
    authority: SourceAuthority,
    layout: StorageLayout,
    source_segment_ids: Sequence[str],
) -> tuple[Path, Mapping[str, Any], bool]:
    attempt_id = _text(authority.payload, "acquisition_attempt_id")
    segments = minute_source_segments(plan)
    expected_ids = tuple(
        _source_segment_identity(plan, authority, segment, attempt_id) for segment in segments
    )
    _validate_source_segment_journal(layout, expected_ids)
    if tuple(source_segment_ids) != expected_ids:
        raise Program002AcquisitionError("minute-source evidence identities differ")
    acquired = tuple(
        _load_source_segment(layout, identity, plan, authority, segment, attempt_id)
        for identity, segment in zip(expected_ids, segments, strict=True)
    )
    reconstruction = derive_minute_reconstruction(
        plan, acquired, load_frozen_five_minute_comparators(plan, layout)
    )
    source_records = tuple(
        _provider_json((layout.dataset(identity) / "segment.json").read_bytes())
        for identity in expected_ids
    )
    retrieval_times = [
        _utc(evidence.get("retrieval_timestamp"))
        for record in source_records
        for evidence in _mapping_sequence(record.get("request_evidence"), "request evidence")
    ]
    artifact: dict[str, Any] = {
        "schema_version": _SOURCE_PROOF_SCHEMA,
        "proof_id": "program-002-minute-reconstruction-source-proof-2026-08-26-v1",
        "program_id": PROGRAM_ID,
        "created_at": _iso(max(retrieval_times)),
        "plan": {
            "path": _PLAN_RELATIVE_PATH.as_posix(),
            "sha256": plan.sha256,
            "fingerprint": plan.fingerprint,
        },
        "source_authority": {
            "path": _SOURCE_AUTHORITY_RELATIVE_PATH.as_posix(),
            "sha256": authority.sha256,
            "fingerprint": authority.fingerprint,
        },
        "acquisition_attempt_id": attempt_id,
        "source_segments": [
            {
                "identity": record["identity"],
                "request": record["request"],
                "content_identity": record["content_identity"],
                "raw_page_sha256_values": record["raw_page_sha256_values"],
                "raw_record_fingerprint": record["raw_record_fingerprint"],
                "minute_record_fingerprint": record["minute_record_fingerprint"],
                "minute_record_count": record["minute_record_count"],
            }
            for record in source_records
        ],
        "frozen_february_quarantine": {
            "identity": _text(
                _mapping(plan.payload["frozen_runtime_lineage"], "runtime lineage"),
                "failed_february_quarantine_identity",
            ),
            "sha256": _text(
                _mapping(plan.payload["frozen_runtime_lineage"], "runtime lineage"),
                "failed_february_quarantine_sha256",
            ),
        },
        "reconstruction": reconstruction,
        "canonical_admission_performed": False,
        "remaining_bar_acquisition_performed": False,
        "quote_acquisition_performed": False,
        "cost_calibration_performed": False,
        "strategy_execution_performed": False,
        "candidate_returns_generated_or_observed": False,
        "authority": {key: False for key in sorted(_AUTHORITY_KEYS)},
    }
    artifact["proof_fingerprint"] = fingerprint(artifact)
    contents = canonical_json(artifact) + "\n"
    path = layout.reports / "program-002" / _SOURCE_PROOF_NAME
    try:
        _publish_report(path, contents)
        created = True
    except FileExistsError:
        if path.read_text(encoding="utf-8") != contents:
            raise Program002AcquisitionError("existing minute-source proof conflicts") from None
        created = False
    return path, artifact, created


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m systematic_trading_lab.program_002_minute_reconstruction"
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("action", choices=("preflight", "acquire-source"))
    parsed = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        plan = load_completeness_source_plan(parsed.repository)
        authority = load_source_authority(parsed.repository, plan)
        source_authority_preflight(plan, authority)
        segments = minute_source_segments(plan)
        if parsed.action == "preflight":
            print(
                json.dumps(
                    {
                        "authority_id": authority.payload["authority_id"],
                        "plan_sha256": plan.sha256,
                        "request_chain_count": len(segments),
                        "status": "preflight-passed",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if parsed.data_home is None:
            raise Program002AcquisitionError("acquire-source requires --data-home")
        layout = StorageLayout(parsed.data_home)
        load_frozen_five_minute_comparators(plan, layout)
        attempt_id = _text(authority.payload, "acquisition_attempt_id")
        _source_attempt_preflight(layout, attempt_id)
        claim_fingerprint = _claim_source_attempt(layout, plan, authority)
        try:
            environment = acquisition_account_environment()
            key, secret = read_acquisition_credentials()
            client = MinuteSourceHttpClient(key, secret, environment, plan, authority, segments)
            completed = acquire_minute_sources(
                plan,
                authority,
                layout,
                client.get,
                claim_fingerprint=claim_fingerprint,
            )
            path, artifact, created = publish_source_proof(plan, authority, layout, completed)
        except (OSError, Program002AcquisitionError, ValueError) as error:
            _seal_source_attempt(
                layout,
                claim_fingerprint,
                "failed-no-retry",
                {"error": str(error)},
            )
            raise
        _seal_source_attempt(
            layout,
            claim_fingerprint,
            "completed-source-proof",
            {"proof_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        )
        print(
            json.dumps(
                {
                    "created": created,
                    "path": str(path),
                    "proof_fingerprint": artifact["proof_fingerprint"],
                    "proof_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "source_segment_count": len(completed),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, Program002AcquisitionError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return os.EX_USAGE


def _verify_frozen_source_scope(plan: CompletenessSourcePlan) -> None:
    selected = _mapping(plan.payload.get("selected_data_source"), "selected data source")
    segments = minute_source_segments(plan)
    targets = _string_sequence(plan.payload.get("exact_derived_coordinates"), "targets")
    if (
        selected.get("provider") != "Alpaca Market Data API"
        or selected.get("endpoint") != f"GET {_BARS}"
        or selected.get("symbol") != "MDY"
        or selected.get("feed") != "sip"
        or selected.get("timeframe") != "1Min"
        or selected.get("adjustment") != "all"
        or selected.get("sort") != "asc"
        or selected.get("limit") != 10000
        or selected.get("start_semantics") != "inclusive"
        or selected.get("end_semantics") != "inclusive"
        or len(segments) != 4
        or len(targets) != 7
        or len(set(targets)) != 7
        or any(segment.endpoint != _BARS or segment.page_ceiling != 100 for segment in segments)
    ):
        raise Program002AcquisitionError("frozen minute-source scope differs")
    expected = _expected_five_minute_coordinates(segments)
    if not set(targets) < expected or len(expected) != 312:
        raise Program002AcquisitionError("frozen minute-source coordinate scope differs")


def _verify_source_authority_bindings(
    repository: Path, plan: CompletenessSourcePlan, payload: Mapping[str, Any]
) -> None:
    expected_authority = {key: False for key in _AUTHORITY_KEYS}
    expected_authority["market_data_acquisition"] = True
    if payload.get("authority") != expected_authority:
        raise Program002AcquisitionError("minute-source authority flags differ")
    bindings = _mapping(payload.get("bindings"), "source authority bindings")
    lineage = _mapping(plan.payload.get("frozen_runtime_lineage"), "runtime lineage")
    expected_static = {
        "completeness_source_plan": {
            "path": _PLAN_RELATIVE_PATH.as_posix(),
            "sha256": plan.sha256,
            "fingerprint": plan.fingerprint,
        },
        "completeness_source_plan_review": {
            "path": _PLAN_REVIEW_RELATIVE_PATH.as_posix(),
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
            "identity": lineage.get("failed_february_quarantine_identity"),
            "sha256": lineage.get("failed_february_quarantine_sha256"),
        },
    }
    if any(bindings.get(key) != value for key, value in expected_static.items()):
        raise Program002AcquisitionError("minute-source authority bindings differ")
    implementation_binding = _mapping(
        bindings.get("implementation_review"), "implementation review binding"
    )
    if implementation_binding.get("path") != _IMPLEMENTATION_REVIEW_RELATIVE_PATH.as_posix():
        raise Program002AcquisitionError("implementation review binding differs")
    implementation_path = repository / _IMPLEMENTATION_REVIEW_RELATIVE_PATH
    implementation_raw = implementation_path.read_bytes()
    _require_sha256(
        implementation_raw,
        _text(implementation_binding, "sha256"),
        "minute reconstruction implementation review",
    )
    implementation = _load_unique_json(
        implementation_raw, "minute reconstruction implementation review"
    )
    implementation_unsigned = dict(implementation)
    implementation_fingerprint = implementation_unsigned.pop("review_fingerprint", None)
    if (
        implementation_binding.get("fingerprint") != implementation_fingerprint
        or implementation_fingerprint != fingerprint(implementation_unsigned)
        or implementation.get("status") != "passed-before-source-authority"
        or implementation.get("verdict") != "pass"
        or implementation.get("findings") != []
    ):
        raise Program002AcquisitionError("minute reconstruction implementation review differs")
    _require_false_authority(implementation.get("authority"), "implementation review")
    source = _mapping(payload.get("source_binding"), "minute-source binding")
    files = source.get("files")
    if (
        not _is_commit(source.get("source_commit"))
        or not isinstance(files, list)
        or [item.get("path") if isinstance(item, Mapping) else None for item in files]
        != list(SOURCE_PATHS)
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"path", "sha256"}
            or not _is_sha256(item.get("sha256"))
            or hashlib.sha256((repository / str(item.get("path"))).read_bytes()).hexdigest()
            != item.get("sha256")
            for item in files
        )
    ):
        raise Program002AcquisitionError("minute-source implementation identity differs")
    reviewed_implementation = _mapping(
        implementation.get("reviewed_implementation"), "reviewed implementation"
    )
    if reviewed_implementation.get("files") != files or reviewed_implementation.get(
        "source_commit"
    ) != source.get("source_commit"):
        raise Program002AcquisitionError("implementation review source differs")
    proof = _load_unique_json(
        (repository / ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH).read_bytes(), "account proof"
    )
    if payload.get("account_isolation") != {
        "proof_accepted": True,
        "environment": proof.get("environment"),
        "account_identity_hash": proof.get("account_identity_hash"),
        "credential_key_id_hash": proof.get("credential_key_id_hash"),
    }:
        raise Program002AcquisitionError("minute-source account binding differs")
    if payload.get("authorized_requests") != [item.url() for item in minute_source_segments(plan)]:
        raise Program002AcquisitionError("minute-source authorized requests differ")
    controls = _mapping(payload.get("controls"), "minute-source controls")
    if set(controls) != _SOURCE_CONTROL_KEYS or controls != {
        "raw_source_acquisition": True,
        "source_proof_publication": True,
        "canonical_admission": False,
        "remaining_bar_acquisition": False,
        "quote_acquisition": False,
        "cost_calibration": False,
    }:
        raise Program002AcquisitionError("minute-source action controls differ")


def _repository_source_preflight(plan: CompletenessSourcePlan, authority: SourceAuthority) -> None:
    repository = plan.repository
    source = _mapping(authority.payload.get("source_binding"), "minute-source binding")
    reviewed = _mapping(authority.review.get("reviewed_source"), "reviewed minute-source")
    source_commit = _text(source, "source_commit")
    authority_commit = _text(reviewed, "authority_artifact_commit")
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    command = (
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository),
    )

    def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (*command, *arguments),
            check=check,
            capture_output=True,
            text=True,
            env=environment,
        )

    try:
        head = git("rev-parse", "HEAD").stdout.strip()
        main_commit = git("rev-parse", "refs/heads/main").stdout.strip()
        origin_main = git("rev-parse", "refs/remotes/origin/main").stdout.strip()
        dirty = git("status", "--porcelain", "--untracked-files=all").stdout
        authority_commits = git(
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            _SOURCE_AUTHORITY_RELATIVE_PATH.as_posix(),
        ).stdout.splitlines()
        review_commits = git(
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            _SOURCE_AUTHORITY_REVIEW_RELATIVE_PATH.as_posix(),
        ).stdout.splitlines()
        if len(authority_commits) != 1 or len(review_commits) != 1:
            raise Program002AcquisitionError("minute-source authority history differs")
        authority_added, review_added = authority_commits[0], review_commits[0]
        ancestry = tuple(
            git("merge-base", "--is-ancestor", earlier, later, check=False).returncode
            for earlier, later in (
                (source_commit, authority_added),
                (authority_added, review_added),
                (review_added, head),
            )
        )
        changed = git("diff", "--name-only", source_commit, head, "--", *SOURCE_PATHS).stdout
        authority_bytes = subprocess.run(
            (*command, "show", f"{authority_added}:{_SOURCE_AUTHORITY_RELATIVE_PATH.as_posix()}"),
            check=True,
            capture_output=True,
            env=environment,
        ).stdout
        review_bytes = subprocess.run(
            (
                *command,
                "show",
                f"{review_added}:{_SOURCE_AUTHORITY_REVIEW_RELATIVE_PATH.as_posix()}",
            ),
            check=True,
            capture_output=True,
            env=environment,
        ).stdout
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise Program002AcquisitionError("minute-source identity is unavailable") from error
    if dirty or head != main_commit or head != origin_main:
        raise Program002AcquisitionError(
            "minute-source acquisition requires clean synchronized main"
        )
    if (
        source_commit != _text(source, "source_commit")
        or authority_commit != authority_added
        or len({source_commit, authority_added, review_added}) != 3
        or any(ancestry)
        or changed
        or authority_bytes != authority.path.read_bytes()
        or review_bytes != authority.review_path.read_bytes()
    ):
        raise Program002AcquisitionError("minute-source reviewed lineage differs")


def _validate_source_segment(
    segment: RequestSegment, acquired: AcquiredSegment
) -> tuple[MinuteBar, ...]:
    if acquired.segment != segment or not acquired.pages or not acquired.raw_records:
        raise Program002AcquisitionError("minute-source evidence is incomplete")
    flattened: list[Mapping[str, Any]] = []
    page_by_coordinate: dict[str, str] = {}
    expected_url = segment.url()
    for index, page in enumerate(acquired.pages):
        if page.request_url != expected_url or page.sha256 != hashlib.sha256(page.body).hexdigest():
            raise Program002AcquisitionError("minute-source page identity differs")
        payload = _provider_json(page.body)
        if set(payload) != {"bars", "next_page_token"}:
            raise Program002AcquisitionError("minute-source page shape differs")
        bars = _mapping(payload.get("bars"), "minute-source bars")
        if set(bars) != {"MDY"} or not isinstance(bars["MDY"], list) or not bars["MDY"]:
            raise Program002AcquisitionError("minute-source page symbol coverage differs")
        for item in bars["MDY"]:
            if not isinstance(item, Mapping):
                raise Program002AcquisitionError("minute-source record is malformed")
            record = {**item, "symbol": "MDY"}
            flattened.append(record)
            coordinate = f"MDY@{_iso(_utc(record.get('t')))}"
            if coordinate in page_by_coordinate:
                raise Program002AcquisitionError("duplicate minute-source coordinate")
            page_by_coordinate[coordinate] = page.sha256
        next_token = payload.get("next_page_token")
        if index + 1 == len(acquired.pages):
            if next_token is not None:
                raise Program002AcquisitionError("minute-source pagination is incomplete")
        else:
            if not isinstance(next_token, str) or not next_token:
                raise Program002AcquisitionError("minute-source page continuation differs")
            expected_url = segment.url(next_token)
    if tuple(flattened) != acquired.raw_records:
        raise Program002AcquisitionError("minute-source raw record evidence differs")
    expected = frozenset(
        expected_bar_timestamps(
            _utc(segment.params["start"]),
            _utc(segment.params["end"]),
            Timeframe.ONE_MINUTE,
        )
    )
    fields: frozenset[str] | None = None
    output: list[MinuteBar] = []
    previous: datetime | None = None
    for raw in acquired.raw_records:
        current_fields = frozenset(str(key) for key in raw)
        if fields is None:
            fields = current_fields
        elif fields != current_fields:
            raise Program002AcquisitionError("minute-source field presence changed")
        required = {"symbol", "t", "o", "h", "l", "c", "v", "n"}
        if not required <= current_fields or raw.get("symbol") != "MDY":
            raise Program002AcquisitionError("minute-source record fields differ")
        timestamp = _utc(raw.get("t"))
        if timestamp not in expected or (previous is not None and timestamp <= previous):
            raise Program002AcquisitionError("minute-source timestamp grid differs")
        previous = timestamp
        open_price = _positive_decimal(raw.get("o"), "minute open")
        high = _positive_decimal(raw.get("h"), "minute high")
        low = _positive_decimal(raw.get("l"), "minute low")
        close = _positive_decimal(raw.get("c"), "minute close")
        if low > min(open_price, close) or high < max(open_price, close) or low > high:
            raise Program002AcquisitionError("minute-source OHLC relationship differs")
        coordinate = f"MDY@{_iso(timestamp)}"
        output.append(
            MinuteBar(
                timestamp,
                open_price,
                high,
                low,
                close,
                _nonnegative_integer(raw.get("v"), "minute volume"),
                _nonnegative_integer(raw.get("n"), "minute trade count"),
                page_by_coordinate[coordinate],
            )
        )
    if not 78 <= len(output) <= 390:
        raise Program002AcquisitionError("minute-source row count differs")
    return tuple(output)


def _aggregate_source_segment(
    segment: RequestSegment, rows: Sequence[MinuteBar]
) -> tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]:
    buckets = expected_bar_timestamps(
        _utc(segment.params["start"]),
        _utc(segment.params["end"]),
        Timeframe.FIVE_MINUTES,
    )
    output: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for bucket in buckets:
        source = tuple(
            item for item in rows if bucket <= item.timestamp < bucket + timedelta(minutes=5)
        )
        if not source:
            raise Program002AcquisitionError(f"minute-source bucket is empty at MDY@{_iso(bucket)}")
        aggregate = canonicalize(
            {
                "timestamp": _iso(bucket),
                "open": source[0].open,
                "high": max(item.high for item in source),
                "low": min(item.low for item in source),
                "close": source[-1].close,
                "volume": sum(item.volume for item in source),
                "trade_count": sum(item.trade_count for item in source),
            }
        )
        ledger = canonicalize(
            {
                "timestamp": _iso(bucket),
                "source_minute_coordinates": [_iso(item.timestamp) for item in source],
                "source_page_sha256_values": sorted({item.page_sha256 for item in source}),
                "aggregate": aggregate,
            }
        )
        assert isinstance(aggregate, dict) and isinstance(ledger, dict)
        output.append((aggregate, ledger))
    if len(output) != 78:
        raise Program002AcquisitionError("minute-source five-minute bucket count differs")
    return tuple(output)


def _five_minute_comparator(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    timestamp = _utc(raw.get("t"))
    result = canonicalize(
        {
            "symbol": "MDY",
            "timestamp": _iso(timestamp),
            "open": _positive_decimal(raw.get("o"), "comparator open"),
            "high": _positive_decimal(raw.get("h"), "comparator high"),
            "low": _positive_decimal(raw.get("l"), "comparator low"),
            "close": _positive_decimal(raw.get("c"), "comparator close"),
            "volume": _nonnegative_integer(raw.get("v"), "comparator volume"),
            "trade_count": _nonnegative_integer(raw.get("n"), "comparator trade count"),
        }
    )
    assert isinstance(result, dict)
    return result


def _source_segment_record(
    plan: CompletenessSourcePlan,
    authority: SourceAuthority,
    segment: RequestSegment,
    acquired: AcquiredSegment,
    attempt_id: str,
    identity: str,
) -> dict[str, Any]:
    minute_rows = _validate_source_segment(segment, acquired)
    raw_bytes = b"".join(canonical_json(item).encode() + b"\n" for item in acquired.raw_records)
    record: dict[str, Any] = {
        "schema_version": _SOURCE_SEGMENT_SCHEMA,
        "identity": identity,
        "acquisition_attempt_id": attempt_id,
        "plan_sha256": plan.sha256,
        "source_authority_sha256": authority.sha256,
        "request": segment.url(),
        "raw_jsonl_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "raw_page_sha256_values": [page.sha256 for page in acquired.pages],
        "raw_record_fingerprint": fingerprint(acquired.raw_records),
        "request_evidence": [page.request_evidence for page in acquired.pages],
        "http_attempts": [list(page.attempts) for page in acquired.pages],
        "minute_record_count": len(minute_rows),
        "minute_record_fingerprint": fingerprint(
            tuple(
                {
                    "timestamp": item.timestamp,
                    "open": item.open,
                    "high": item.high,
                    "low": item.low,
                    "close": item.close,
                    "volume": item.volume,
                    "trade_count": item.trade_count,
                    "page_sha256": item.page_sha256,
                }
                for item in minute_rows
            )
        ),
        "five_minute_bucket_count": 78,
    }
    record["content_identity"] = fingerprint(record)
    return record


def _load_source_segment(
    layout: StorageLayout,
    identity: str,
    plan: CompletenessSourcePlan,
    authority: SourceAuthority,
    segment: RequestSegment,
    attempt_id: str,
) -> AcquiredSegment:
    root = layout.dataset(identity)
    try:
        artifact = _provider_json((root / "segment.json").read_bytes())
        raw_bytes = (root / "raw-records.jsonl").read_bytes()
    except OSError as error:
        raise Program002AcquisitionError("stored minute-source segment is incomplete") from error
    pages = tuple(sorted(root.glob("raw-page-*.json")))
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in pages]
    evidence = artifact.get("request_evidence")
    attempts = artifact.get("http_attempts")
    expected_names = tuple(f"raw-page-{index:04d}.json" for index in range(1, len(pages) + 1))
    if (
        artifact.get("schema_version") != _SOURCE_SEGMENT_SCHEMA
        or artifact.get("identity") != identity
        or artifact.get("acquisition_attempt_id") != attempt_id
        or artifact.get("plan_sha256") != plan.sha256
        or artifact.get("source_authority_sha256") != authority.sha256
        or artifact.get("request") != segment.url()
        or artifact.get("raw_jsonl_sha256") != hashlib.sha256(raw_bytes).hexdigest()
        or artifact.get("raw_page_sha256_values") != hashes
        or not isinstance(evidence, list)
        or not isinstance(attempts, list)
        or len(evidence) != len(pages)
        or len(attempts) != len(pages)
        or tuple(path.name for path in pages) != expected_names
        or artifact.get("content_identity")
        != fingerprint({key: value for key, value in artifact.items() if key != "content_identity"})
    ):
        raise Program002AcquisitionError("stored minute-source segment conflicts")
    try:
        records = tuple(
            _provider_json(line.encode()) for line in raw_bytes.decode("utf-8").splitlines()
        )
    except UnicodeDecodeError as error:
        raise Program002AcquisitionError("stored minute-source records are not UTF-8") from error
    if artifact.get("raw_record_fingerprint") != fingerprint(records):
        raise Program002AcquisitionError("stored minute-source record integrity differs")
    acquired = AcquiredSegment(
        segment,
        tuple(
            RawPage(
                _text(request, "request_url"),
                path.read_bytes(),
                digest,
                request,
                tuple(page_attempts),
            )
            for path, digest, request, page_attempts in zip(
                pages, hashes, evidence, attempts, strict=True
            )
        ),
        records,
        (),
    )
    if _source_segment_record(plan, authority, segment, acquired, attempt_id, identity) != artifact:
        raise Program002AcquisitionError("stored minute-source processing differs")
    return acquired


def _source_segment_identity(
    plan: CompletenessSourcePlan,
    authority: SourceAuthority,
    segment: RequestSegment,
    attempt_id: str,
) -> str:
    return fingerprint(
        {
            "plan_sha256": plan.sha256,
            "source_authority_sha256": authority.sha256,
            "acquisition_attempt_id": attempt_id,
            "request": segment.url(),
        }
    )


def _source_attempt_preflight(layout: StorageLayout, attempt_id: str) -> None:
    path = layout.reports / "program-002" / "minute-source-terminal-attempts.jsonl"
    if not path.exists():
        return
    try:
        lines = path.read_bytes().splitlines()
        records = tuple(_provider_json(line) for line in lines)
    except (OSError, Program002AcquisitionError) as error:
        raise Program002AcquisitionError("minute-source terminal journal differs") from error
    for record in records:
        unsigned = dict(record)
        identity = unsigned.pop("identity", None)
        quarantine_identity = record.get("quarantine_identity")
        if (
            identity != fingerprint(unsigned)
            or record.get("schema_version") != "program-002-minute-source-terminal-attempt-v1"
            or record.get("disposition") != "failed-no-retry"
            or not _is_sha256(quarantine_identity)
        ):
            raise Program002AcquisitionError("minute-source terminal journal differs")
        try:
            quarantine_raw = (layout.quarantine / f"{quarantine_identity}.json").read_bytes()
            quarantine = _provider_json(quarantine_raw)
        except OSError as error:
            raise Program002AcquisitionError(
                "minute-source quarantine evidence is absent"
            ) from error
        if (
            fingerprint(quarantine) != quarantine_identity
            or quarantine_raw != (canonical_json(quarantine) + "\n").encode()
        ):
            raise Program002AcquisitionError("minute-source quarantine evidence differs")
        if record.get("acquisition_attempt_id") == attempt_id:
            raise Program002AcquisitionError("minute-source authority is terminal after failure")


def _claim_source_attempt(
    layout: StorageLayout, plan: CompletenessSourcePlan, authority: SourceAuthority
) -> str:
    record: dict[str, Any] = {
        "schema_version": "program-002-minute-source-attempt-claim-v1",
        "acquisition_attempt_id": _text(authority.payload, "acquisition_attempt_id"),
        "plan_sha256": plan.sha256,
        "source_authority_sha256": authority.sha256,
        "authorized_requests": [item.url() for item in minute_source_segments(plan)],
        "claimed_at": _iso(datetime.now(UTC)),
        "disposition": "claimed-one-use-terminal-on-interruption",
    }
    record["claim_fingerprint"] = fingerprint(record)
    path = layout.reports / "program-002" / "minute-source-attempt-claim-v1.json"
    try:
        _publish_report(path, canonical_json(record) + "\n")
    except FileExistsError:
        raise Program002AcquisitionError("minute-source attempt is already claimed") from None
    return str(record["claim_fingerprint"])


def _start_source_attempt(
    layout: StorageLayout,
    plan: CompletenessSourcePlan,
    authority: SourceAuthority,
    claim_fingerprint: str,
) -> None:
    claim_path = layout.reports / "program-002" / "minute-source-attempt-claim-v1.json"
    try:
        claim = _provider_json(claim_path.read_bytes())
    except OSError as error:
        raise Program002AcquisitionError("minute-source attempt claim is absent") from error
    unsigned = dict(claim)
    stored_fingerprint = unsigned.pop("claim_fingerprint", None)
    if (
        stored_fingerprint != claim_fingerprint
        or stored_fingerprint != fingerprint(unsigned)
        or claim.get("schema_version") != "program-002-minute-source-attempt-claim-v1"
        or claim.get("acquisition_attempt_id") != _text(authority.payload, "acquisition_attempt_id")
        or claim.get("plan_sha256") != plan.sha256
        or claim.get("source_authority_sha256") != authority.sha256
        or claim.get("authorized_requests") != [item.url() for item in minute_source_segments(plan)]
        or claim.get("disposition") != "claimed-one-use-terminal-on-interruption"
    ):
        raise Program002AcquisitionError("minute-source attempt claim differs")
    existing = _validate_source_segment_journal(layout)
    expected_ids = {
        _source_segment_identity(
            plan,
            authority,
            segment,
            _text(authority.payload, "acquisition_attempt_id"),
        )
        for segment in minute_source_segments(plan)
    }
    if existing or any(layout.dataset(identity).exists() for identity in expected_ids):
        raise Program002AcquisitionError("minute-source evidence predates the one-use claim")
    start = {
        "schema_version": "program-002-minute-source-attempt-start-v1",
        "claim_fingerprint": claim_fingerprint,
        "disposition": "started-no-retry",
    }
    start["start_fingerprint"] = fingerprint(start)
    path = layout.reports / "program-002" / "minute-source-attempt-start-v1.json"
    try:
        _publish_report(path, canonical_json(start) + "\n")
    except FileExistsError:
        raise Program002AcquisitionError("minute-source attempt already started") from None


def _seal_source_attempt(
    layout: StorageLayout,
    claim_fingerprint: str,
    disposition: str,
    evidence: Mapping[str, Any],
) -> None:
    if disposition not in {"completed-source-proof", "failed-no-retry"}:
        raise ValueError("minute-source outcome disposition differs")
    record: dict[str, Any] = {
        "schema_version": "program-002-minute-source-attempt-outcome-v1",
        "claim_fingerprint": claim_fingerprint,
        "disposition": disposition,
        "evidence": dict(evidence),
    }
    record["outcome_fingerprint"] = fingerprint(record)
    path = layout.reports / "program-002" / "minute-source-attempt-outcome-v1.json"
    contents = canonical_json(record) + "\n"
    try:
        _publish_report(path, contents)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != contents:
            raise Program002AcquisitionError("minute-source attempt outcome conflicts") from None


def _append_source_failure(
    layout: StorageLayout,
    attempt_id: str,
    segment: RequestSegment,
    error: Program002AcquisitionError,
    segment_identity: str,
    quarantine_identity: str | None,
) -> None:
    record: dict[str, Any] = {
        "schema_version": "program-002-minute-source-terminal-attempt-v1",
        "acquisition_attempt_id": attempt_id,
        "request": segment.url(),
        "disposition": "failed-no-retry",
        "error": str(error),
        "segment_identity": segment_identity,
        "quarantine_identity": quarantine_identity,
        "http_attempts": list(getattr(error, "http_attempts", ())),
    }
    record["identity"] = fingerprint(record)
    path = layout.reports / "program-002" / "minute-source-terminal-attempts.jsonl"
    _append_jsonl(path, record)


def _append_source_segment_journal(layout: StorageLayout, record: Mapping[str, Any]) -> None:
    _append_jsonl(layout.reports / "program-002" / "minute-source-segments.jsonl", record)


def _validate_source_segment_journal(
    layout: StorageLayout, expected_identities: Sequence[str] = ()
) -> dict[str, Mapping[str, Any]]:
    path = layout.reports / "program-002" / "minute-source-segments.jsonl"
    if not path.exists():
        if expected_identities:
            raise Program002AcquisitionError("minute-source journal is absent")
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError, Program002AcquisitionError) as error:
        raise Program002AcquisitionError("minute-source journal differs") from error
    if lines and not lines[-1].endswith("\n"):
        try:
            _provider_json(lines[-1].encode())
        except Program002AcquisitionError:
            lines.pop()
        else:
            lines[-1] += "\n"
        _rewrite_jsonl(path, lines)
    try:
        records = tuple(_provider_json(line.encode()) for line in lines)
    except Program002AcquisitionError as error:
        raise Program002AcquisitionError("minute-source journal differs") from error
    output: dict[str, Mapping[str, Any]] = {}
    for record in records:
        identity = record.get("identity")
        if not isinstance(identity, str) or identity in output:
            raise Program002AcquisitionError("minute-source journal identity differs")
        try:
            stored = _provider_json((layout.dataset(identity) / "segment.json").read_bytes())
        except OSError as error:
            raise Program002AcquisitionError(
                "minute-source journal references missing artifact"
            ) from error
        if stored != record:
            raise Program002AcquisitionError("minute-source journal artifact differs")
        output[identity] = record
    if expected_identities and set(output) != set(expected_identities):
        raise Program002AcquisitionError("minute-source journal segment set differs")
    return output


def _rewrite_jsonl(path: Path, lines: Sequence[str]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.repair-", dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(record) + "\n"
    if path.exists() and line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        return
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _quarantine_source_segment(
    layout: StorageLayout,
    segment: RequestSegment,
    acquired: AcquiredSegment,
    error: Exception,
    attempt_id: str,
    identity: str,
) -> str:
    evidence = {
        "schema_version": "program-002-minute-source-quarantine-v1",
        "acquisition_attempt_id": attempt_id,
        "segment_identity": identity,
        "request": segment.url(),
        "raw_pages": [
            {
                "request_url": page.request_url,
                "sha256": page.sha256,
                "body_hex": page.body.hex(),
                "request_evidence": page.request_evidence,
                "http_attempts": page.attempts,
            }
            for page in acquired.pages
        ],
        "raw_records": list(acquired.raw_records),
        "validation_error": str(error),
    }
    quarantine_identity = fingerprint(evidence)
    layout.write_quarantine(quarantine_identity, canonical_json(evidence) + "\n")
    return quarantine_identity


def _expected_five_minute_coordinates(
    segments: Sequence[RequestSegment],
) -> set[str]:
    return {
        f"MDY@{_iso(timestamp)}"
        for segment in segments
        for timestamp in expected_bar_timestamps(
            _utc(segment.params["start"]),
            _utc(segment.params["end"]),
            Timeframe.FIVE_MINUTES,
        )
    }


def _request_identity(
    url: str, *, allow_page_token: bool
) -> tuple[str, tuple[tuple[str, str], ...]]:
    parsed = urlparse(url)
    if parsed.params or parsed.fragment or parsed.username or parsed.password:
        raise Program002AcquisitionError("minute-source request differs from reviewed scope")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    tokens = [value for key, value in query if key == "page_token"]
    if len(tokens) > 1 or (tokens and (not allow_page_token or not tokens[0])):
        raise Program002AcquisitionError("minute-source request differs from reviewed scope")
    return parsed.path, tuple(sorted((key, value) for key, value in query if key != "page_token"))


def _provider_json(raw: bytes) -> Mapping[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Program002AcquisitionError("provider JSON contains duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid constant {value}")
            ),
        )
    except (ArithmeticError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise Program002AcquisitionError("provider evidence JSON is malformed") from error
    return _mapping(value, "provider evidence")


def _load_unique_json(raw: bytes, label: str) -> Mapping[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Program002AcquisitionError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program002AcquisitionError(f"{label} is invalid JSON") from error
    return _mapping(value, label)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program002AcquisitionError(f"{label} must be an object")
    return value


def _mapping_sequence(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise Program002AcquisitionError(f"{label} must be a list of objects")
    return tuple(value)


def _string_sequence(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Program002AcquisitionError(f"{label} must be a list of text")
    return tuple(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise Program002AcquisitionError(f"{key} must be text")
    return item


def _decimal(value: object, label: str) -> Decimal:
    try:
        output = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as error:
        raise Program002AcquisitionError(f"{label} is malformed") from error
    if not output.is_finite():
        raise Program002AcquisitionError(f"{label} is non-finite")
    return output


def _positive_decimal(value: object, label: str) -> Decimal:
    output = _decimal(value, label)
    if output <= 0:
        raise Program002AcquisitionError(f"{label} is not positive")
    return output


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Program002AcquisitionError(f"{label} is not an integer")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    output = _integer(value, label)
    if output < 0:
        raise Program002AcquisitionError(f"{label} is negative")
    return output


def _utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise Program002AcquisitionError("provider timestamp is malformed") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Program002AcquisitionError("provider timestamp must be UTC")
    return parsed


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_sha256(raw: bytes, expected: str, label: str) -> None:
    if hashlib.sha256(raw).hexdigest() != expected:
        raise Program002AcquisitionError(f"{label} SHA-256 differs")


def _require_false_authority(value: object, label: str) -> None:
    authority = _mapping(value, f"{label} authority")
    if set(authority) != _AUTHORITY_KEYS or any(item is not False for item in authority.values()):
        raise Program002AcquisitionError(f"{label} authority differs")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_commit(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _publish_report(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _urlopen_page(request: Request) -> HttpPage:
    from .program_002_acquisition import _urlopen_page

    return _urlopen_page(request)


if __name__ == "__main__":
    raise SystemExit(main())
