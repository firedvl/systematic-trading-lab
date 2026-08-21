"""Strict preregistration loader for Intraday Exposed 002."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import Timeframe
from .fingerprints import fingerprint
from .intraday_execution_cost_model import load_intraday_execution_cost_model

PLAN_ID = "intraday-exposed-002"
PLAN_SCHEMA = "intraday-exposed-002-research-plan-v1"
PLAN_RELATIVE_PATH = Path("config/research/intraday-exposed-002-plan-v1.json")
REVIEWED_PLAN_SHA256 = "8acb778eec43dd53b56c65712b5a076bdc6126de3504d68114aa714e2474b17f"
REVIEWED_PLAN_FINGERPRINT = "a255949e41c9776e82a04782c6183f5af1476a1dc97c36be4910e4d59424fb98"
PLAN_REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-002-plan-independent-review-v1.json"
)
REVIEWED_PLAN_REVIEW_SHA256 = "7a87b647aaf420a8613b793f26bc948c5572e6d66907f9aa9c330e9c543fafb0"
REVIEWED_PLAN_REVIEW_FINGERPRINT = (
    "2ecd5227c3ddc51de9725484de21c994a930dc6f83b7c866d886b68185efdcc4"
)
PLAN_AMENDMENT_RELATIVE_PATH = Path("config/research/intraday-exposed-002-plan-amendment-v2.json")
REVIEWED_PLAN_AMENDMENT_SHA256 = "d6409531b31d25c4f3bcd79a55b2bf22b359ca71e4a0fada346ba06dbf0bc14b"
REVIEWED_PLAN_AMENDMENT_FINGERPRINT = (
    "e02a23d078f5b4d7216f7b1ede6dab0c2b85859e8e56c4781da5fa32a6429e00"
)
PLAN_AMENDMENT_REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-002-plan-amendment-independent-review-v2.json"
)
REVIEWED_PLAN_AMENDMENT_REVIEW_SHA256 = (
    "a739b1e5bb82d0c03640e5d9fd13a4d1edc3b77c1865ed7a065520f9d3c11aa3"
)
REVIEWED_PLAN_AMENDMENT_REVIEW_FINGERPRINT = (
    "38a359ce9eb04243ba4092e7eb70c7239a46ac738de3ccbd09b6ddde31325976"
)
MAY_ACQUISITION_DISPOSITION_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-002-may-acquisition-disposition-v1.json"
)
REVIEWED_MAY_ACQUISITION_DISPOSITION_SHA256 = (
    "eca321176b609e5b2e9069b7364a1d61979998899b8ef6c4dc4c75d457816707"
)
REVIEWED_MAY_ACQUISITION_DISPOSITION_FINGERPRINT = (
    "3715a0f424e7450976b1d17f0118906ab9c862e601fcb2c226d98916465df7b3"
)
DATA_BINDING_RELATIVE_PATH = Path("config/research/intraday-exposed-002-data-binding-v1.json")
REVIEWED_DATA_BINDING_SHA256 = "3d6a5dde3b05369ceeb1e3be5b1f47e73a541c74eed184e1850945ee56890769"
REVIEWED_DATA_BINDING_FINGERPRINT = (
    "b6849987e7673c4073272ec891e7f7118b91eba6926aa4c16f262162f529ea9d"
)
DATA_BINDING_REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-002-data-binding-independent-review-v1.json"
)
REVIEWED_DATA_BINDING_REVIEW_SHA256 = (
    "16e1ae6bc4f718f5086eec15dfcdab61fa1a2ca57ce85dab73de8fbb045e3701"
)
REVIEWED_DATA_BINDING_REVIEW_FINGERPRINT = (
    "bae2ed10678d5a18c916773b1dcfe0b11d3b26f1f7ec2d2ec9e88dd88965d444"
)
JUNE_DISPOSITION_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-002-june-disposition-v2.json"
)
REVIEWED_JUNE_DISPOSITION_SHA256 = (
    "a3b623a6ab070a8f33cc5d032bf4ab944e9e2d971405c95f4b220e758c5250f0"
)
REVIEWED_JUNE_DISPOSITION_FINGERPRINT = (
    "7c8a2ea44a3f6679d5cc7ca72b0aee509073272723755c8fea99b09b85de477d"
)

_STARTING_MAIN = "71aa4da11875cffbff77693be83d116d11a5cb73"
_AMENDMENT_STARTING_MAIN = "1aedc2d4056c955a8fdd835a1795277979c94be4"
_DATA_BINDING_STARTING_MAIN = "01430416953559e0168a2192afb3f859440bc7a4"
_PLAN_STATUS = "frozen-before-may-only-data-acquisition-or-strategy-results"
_PRE_MAY_DATA_END = datetime.fromisoformat("2026-04-30T19:55:00+00:00")
_MAY_START = datetime.fromisoformat("2026-05-01T13:30:00+00:00")
_LATEST_PERMITTED_BAR = datetime.fromisoformat("2026-05-29T19:55:00+00:00")
_EXISTING_DATA_RANGES = (
    (
        datetime.fromisoformat("2025-07-01T13:30:00+00:00"),
        datetime.fromisoformat("2025-12-31T20:55:00+00:00"),
    ),
    (
        datetime.fromisoformat("2026-01-02T14:30:00+00:00"),
        datetime.fromisoformat("2026-02-27T20:55:00+00:00"),
    ),
    (
        datetime.fromisoformat("2026-03-02T14:30:00+00:00"),
        _PRE_MAY_DATA_END,
    ),
)
_DATA_BINDING_FIELDS = [
    "dataset_id",
    "fingerprint",
    "raw_fingerprint",
    "raw_sha256",
    "manifest_sha256",
    "bars_sha256",
    "requested_start",
    "requested_end",
    "actual_start",
    "actual_end",
    "session_count",
    "bar_count",
    "acquisition_main",
    "physically_bounded_before_june",
]
_AMENDMENT_DATA_BINDING_FIELDS = [
    "dataset_id",
    "fingerprint",
    "raw_fingerprint",
    "raw_sha256",
    "manifest_sha256",
    "bars_sha256",
    "requested_start",
    "requested_end",
    "actual_start",
    "actual_end",
    "raw_start",
    "raw_end",
    "raw_record_count",
    "raw_outside_regular_grid_count",
    "session_count",
    "bar_count",
    "acquisition_main",
    "contains_june_market_timestamp",
]
_AMENDMENT_BINDING_STATUS = (
    "must-be-frozen-and-independently-reviewed-after-this-amendment-merges-before-strategy-results"
)
_AUTHORITY = {
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_AMENDMENT_AUTHORITY = {
    "data_binding": False,
    "strategy_results": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_DATA_BINDING_AUTHORITY = {
    "strategy_results": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_FAMILY_IDS = (
    "gap-down-failed-continuation-fade-v1",
    "gap-up-confirmed-continuation-v1",
    "opening-range-breakout-v1",
    "volatility-compression-breakout-v1",
    "trend-pullback-recovery-v1",
    "prior-session-level-event-v1",
    "morning-afternoon-continuation-v1",
    "cross-asset-confirmed-breakout-v1",
    "volatility-filtered-breakout-v1",
    "minimum-edge-hysteresis-one-trade-v1",
)
_DISCOVERY_METRICS = {
    "normal.total_return",
    "zero_cost_diagnostic.total_return",
    "normal.completed_round_trips",
    "normal.average_round_trips_per_session",
    "normal.max_drawdown",
    "normal.cost_to_gross_profit",
    "normal.average_gross_trade_edge_bps",
    "normal.average_holding_bars",
    "normal.positive_profit_symbol_concentration",
    "normal.accounting_identity_error",
}
_WALK_FORWARD_METRICS = {
    "aggregate.normal.total_return",
    "positive_normal_fold_count",
    "final_exposed_may.normal.total_return",
    "worst_normal_fold_return",
    "worst_normal_fold_drawdown",
    "aggregate.normal.completed_round_trips",
    "aggregate.normal.average_round_trips_per_session",
    "aggregate.normal.cost_to_gross_profit",
    "aggregate.normal.average_gross_trade_edge_bps",
    "aggregate.normal.average_holding_bars",
    "aggregate.normal.positive_profit_symbol_concentration",
    "aggregate.normal.accounting_identity_error",
}
_STRESS_METRICS = {
    f"{scenario}.{metric}"
    for scenario in ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
    for metric in ("aggregate_total_return", "positive_fold_count", "normal_profit_retention")
}


@dataclass(frozen=True)
class Exposed002Configuration:
    candidate_id: str
    family_id: str
    family_ordinal: int
    parameters: Mapping[str, object]
    neighbor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class Exposed002Period:
    period_id: str
    context_start: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    session_count: int


@dataclass(frozen=True)
class IntradayExposed002Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    amendment_path: Path
    amendment_sha256: str
    amendment_fingerprint: str
    data_binding_path: Path
    data_binding_sha256: str
    data_binding_fingerprint: str
    payload: Mapping[str, Any]
    amendment: Mapping[str, Any]
    data_binding: Mapping[str, Any]
    configurations: tuple[Exposed002Configuration, ...]
    periods: tuple[Exposed002Period, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "amendment", MappingProxyType(dict(self.amendment)))
        object.__setattr__(self, "data_binding", MappingProxyType(dict(self.data_binding)))


def load_intraday_exposed_002_plan(repository: Path) -> IntradayExposed002Plan:
    repository = repository.resolve()
    path = repository / PLAN_RELATIVE_PATH
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != REVIEWED_PLAN_SHA256:
        raise ValueError("Intraday Exposed 002 plan SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw), "Intraday Exposed 002 plan")
    except json.JSONDecodeError as error:
        raise ValueError("Intraday Exposed 002 plan is invalid JSON") from error
    stored_fingerprint = _text(payload, "plan_fingerprint")
    unsigned = dict(payload)
    del unsigned["plan_fingerprint"]
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_PLAN_FINGERPRINT
    ):
        raise ValueError("Intraday Exposed 002 plan fingerprint differs")
    if (
        payload.get("schema_version") != PLAN_SCHEMA
        or payload.get("program_id") != PLAN_ID
        or payload.get("status") != _PLAN_STATUS
        or payload.get("starting_main") != _STARTING_MAIN
        or payload.get("authority") != _AUTHORITY
    ):
        raise ValueError("Intraday Exposed 002 plan identity differs")

    _verify_dependencies(repository, payload)
    _verify_plan_review(repository, sha256, stored_fingerprint)
    amendment_path, amendment_sha256, amendment_fingerprint, amendment = _load_plan_amendment(
        repository, payload, sha256, stored_fingerprint
    )
    _verify_plan_amendment_review(repository, amendment_sha256, amendment_fingerprint)
    data_binding_path, data_binding_sha256, data_binding_fingerprint, data_binding = (
        _load_data_binding(repository, payload, amendment, amendment_sha256, amendment_fingerprint)
    )
    _verify_data_binding_review(repository, data_binding_sha256, data_binding_fingerprint)
    periods = _periods(payload)
    configurations = _configurations(payload)
    _verify_data_boundary(payload, periods)
    _verify_screens(payload)
    _verify_controlled_boundary(payload)
    return IntradayExposed002Plan(
        path,
        sha256,
        stored_fingerprint,
        amendment_path,
        amendment_sha256,
        amendment_fingerprint,
        data_binding_path,
        data_binding_sha256,
        data_binding_fingerprint,
        payload,
        amendment,
        data_binding,
        configurations,
        periods,
    )


def _verify_dependencies(repository: Path, payload: Mapping[str, Any]) -> None:
    dependencies = _mapping(payload.get("frozen_dependencies"), "frozen dependencies")
    cost = _mapping(dependencies.get("execution_cost_model"), "execution cost model")
    model = load_intraday_execution_cost_model(repository)
    if (
        cost.get("path") != model.path.relative_to(repository).as_posix()
        or cost.get("cost_model_id") != model.payload.get("cost_model_id")
        or cost.get("sha256") != model.sha256
        or cost.get("fingerprint") != model.model_fingerprint
    ):
        raise ValueError("Intraday Exposed 002 cost-model dependency differs")

    review = _mapping(dependencies.get("execution_cost_review"), "execution cost review")
    _verify_artifact(
        repository,
        review,
        "review_fingerprint",
        "8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2",
    )
    if review.get("verdict") != "pass":
        raise ValueError("Intraday Exposed 002 cost review did not pass")

    disposition = _mapping(dependencies.get("june_disposition"), "June disposition")
    value = _verify_artifact(
        repository,
        disposition,
        "disposition_fingerprint",
        REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
    )
    if (
        disposition.get("path") != JUNE_DISPOSITION_RELATIVE_PATH.as_posix()
        or disposition.get("sha256") != REVIEWED_JUNE_DISPOSITION_SHA256
        or disposition.get("status") != "ineligible-before-strategy-results"
        or value.get("status") != disposition.get("status")
        or _mapping(value.get("program_effect"), "June program effect").get("june_read_allowed")
        is not False
    ):
        raise ValueError("Intraday Exposed 002 June disposition differs")


def _verify_plan_review(repository: Path, plan_sha256: str, plan_fingerprint: str) -> None:
    path = repository / PLAN_REVIEW_RELATIVE_PATH
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_PLAN_REVIEW_SHA256:
        raise ValueError("Intraday Exposed 002 plan-review SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 plan review")
    stored_fingerprint = _text(value, "review_fingerprint")
    unsigned = dict(value)
    del unsigned["review_fingerprint"]
    reviewed_plan = _mapping(value.get("reviewed_plan"), "reviewed plan")
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_PLAN_REVIEW_FINGERPRINT
        or value.get("schema_version") != "intraday-exposed-002-plan-independent-review-v1"
        or value.get("status") != "passed-before-may-only-data-acquisition-or-strategy-results"
        or value.get("verdict") != "pass"
        or value.get("findings") != []
        or reviewed_plan.get("program_id") != PLAN_ID
        or reviewed_plan.get("path") != PLAN_RELATIVE_PATH.as_posix()
        or reviewed_plan.get("sha256") != plan_sha256
        or reviewed_plan.get("plan_fingerprint") != plan_fingerprint
    ):
        raise ValueError("Intraday Exposed 002 plan review differs")


def _load_plan_amendment(
    repository: Path,
    base_payload: Mapping[str, Any],
    base_sha256: str,
    base_fingerprint: str,
) -> tuple[Path, str, str, Mapping[str, Any]]:
    path = repository / PLAN_AMENDMENT_RELATIVE_PATH
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != REVIEWED_PLAN_AMENDMENT_SHA256:
        raise ValueError("Intraday Exposed 002 plan-amendment SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 plan amendment")
    stored_fingerprint = _text(value, "amendment_fingerprint")
    unsigned = dict(value)
    del unsigned["amendment_fingerprint"]
    base = _mapping(value.get("base_plan"), "base plan")
    disposition_binding = _mapping(value.get("acquisition_disposition"), "acquisition disposition")
    disposition = _verify_artifact(
        repository,
        disposition_binding,
        "disposition_fingerprint",
        REVIEWED_MAY_ACQUISITION_DISPOSITION_FINGERPRINT,
    )
    replacement = _mapping(value.get("replacement_data_contract"), "replacement contract")
    source_request = _mapping(replacement.get("source_request"), "source request")
    bound = _mapping(replacement.get("bound_acquisition"), "bound acquisition")
    raw_transport = _mapping(replacement.get("raw_transport"), "raw transport")
    normalized = _mapping(replacement.get("normalized_parquet"), "normalized Parquet")
    manifest = _mapping(replacement.get("manifest"), "manifest")
    required_binding = _mapping(value.get("required_data_binding"), "required data binding")
    gates = _mapping(value.get("execution_gates"), "execution gates")
    published = _mapping(disposition.get("published_dataset"), "published dataset")
    program_effect = _mapping(disposition.get("program_effect"), "program effect")
    superseded = _mapping(value.get("superseded_rule"), "superseded rule")
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_PLAN_AMENDMENT_FINGERPRINT
        or value.get("schema_version") != "intraday-exposed-002-research-plan-amendment-v2"
        or value.get("amendment_id") != "intraday-exposed-002-plan-amendment-v2"
        or value.get("program_id") != PLAN_ID
        or value.get("status")
        != "frozen-after-transport-boundary-finding-before-data-binding-or-strategy-results"
        or value.get("starting_main") != _AMENDMENT_STARTING_MAIN
        or value.get("authority") != _AMENDMENT_AUTHORITY
        or base
        != {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": base_sha256,
            "plan_fingerprint": base_fingerprint,
            "review_path": PLAN_REVIEW_RELATIVE_PATH.as_posix(),
            "review_sha256": REVIEWED_PLAN_REVIEW_SHA256,
            "review_fingerprint": REVIEWED_PLAN_REVIEW_FINGERPRINT,
        }
        or disposition_binding.get("path") != MAY_ACQUISITION_DISPOSITION_RELATIVE_PATH.as_posix()
        or disposition_binding.get("sha256") != REVIEWED_MAY_ACQUISITION_DISPOSITION_SHA256
        or disposition_binding.get("status") != "closed-pre-result-acquisition-contract-mismatch"
        or disposition.get("status") != disposition_binding.get("status")
        or superseded.get("path") != "data.may_only_acquisition.publication_rule"
        or superseded.get("value")
        != _mapping(
            _mapping(base_payload.get("data"), "base data").get("may_only_acquisition"),
            "base May acquisition",
        ).get("publication_rule")
        or source_request
        != {
            "method": "GET",
            "provider": "alpaca-historical-v2",
            "feed": "iex",
            "symbols": ["QQQ", "SPY"],
            "timeframe": "5m",
            "requested_start": "2026-05-01T13:30:00Z",
            "requested_end": "2026-05-29T19:55:00Z",
            "adjustment_policy": "provider-adjusted-all-v1",
            "fallback_used": False,
            "existing_artifact_derivation_used": False,
        }
        or bound
        != {
            "dataset_id": "4afa60f29ea266ec8b60be9d9600132f8cff4207e846443c65afd3bb5c497a19",
            "fingerprint": "d34de04b0045967396266bfba7c3427b5fac949d5e1800c0d5fe5b3fc454e29c",
            "raw_fingerprint": ("9c0fa665f1afcf9f5355758d5dfe17b49e090671812132cc00612d337b96f5a5"),
            "raw_sha256": "e5fd2680c7915f4673e1735f860473c37e32ceaa57f7876111310d0ac5c87ad2",
            "bars_sha256": "74ce7f13971564b4d7d42e0e7adfc1811ed026498cbed9fac7e79864d1afdb44",
            "manifest_sha256": ("027714eeb34f274c6b887c1fefecdd72b18d24ef505a906a9d5137bdc8e2ee5f"),
            "acquisition_main": _AMENDMENT_STARTING_MAIN,
        }
        or raw_transport
        != {
            "retain_every_mapped_transport_record": True,
            "record_count": 3503,
            "outside_regular_grid_count": 383,
            "actual_start": "2026-05-01T13:30:00Z",
            "actual_end": "2026-05-29T20:00:00Z",
            "exclusive_latest_permitted_timestamp": "2026-06-01T00:00:00Z",
            "contains_june_market_timestamp": False,
            "deletion_or_filtering_allowed": False,
        }
        or normalized
        != {
            "bar_count": 3120,
            "session_count": 20,
            "actual_start": "2026-05-01T13:30:00Z",
            "actual_end": "2026-05-29T19:55:00Z",
            "exact_xnys_regular_grid_required": True,
            "full_dataset_validation_required": True,
            "contains_june_market_timestamp": False,
        }
        or manifest
        != {
            "requested_start": "2026-05-01T13:30:00Z",
            "requested_end": "2026-05-29T19:55:00Z",
            "actual_start": "2026-05-01T13:30:00Z",
            "actual_end": "2026-05-29T19:55:00Z",
            "provider": "alpaca-historical-v2",
            "feed": "iex",
            "timeframe": "5m",
        }
        or required_binding.get("path")
        != "config/research/intraday-exposed-002-data-binding-v1.json"
        or required_binding.get("status") != _AMENDMENT_BINDING_STATUS
        or required_binding.get("required_fields") != _AMENDMENT_DATA_BINDING_FIELDS
        or gates
        != {
            "amendment_independent_review_required": True,
            "amendment_merge_required": True,
            "data_binding_and_independent_review_required": True,
            "runner_implementation_and_merge_required": True,
            "strategy_execution_allowed_now": False,
        }
        or program_effect.get("bind_under_plan_v1") is not False
        or program_effect.get("strategy_execution_allowed") is not False
        or published.get("dataset_id") != bound.get("dataset_id")
        or published.get("fingerprint") != bound.get("fingerprint")
        or published.get("raw_fingerprint") != bound.get("raw_fingerprint")
        or published.get("raw_sha256") != bound.get("raw_sha256")
        or published.get("bars_sha256") != bound.get("bars_sha256")
        or published.get("manifest_sha256") != bound.get("manifest_sha256")
        or published.get("raw_record_count") != raw_transport.get("record_count")
        or published.get("raw_outside_regular_grid_count")
        != raw_transport.get("outside_regular_grid_count")
        or published.get("bar_count") != normalized.get("bar_count")
        or published.get("session_count") != normalized.get("session_count")
    ):
        raise ValueError("Intraday Exposed 002 plan amendment differs")
    return path, sha256, stored_fingerprint, value


def _verify_plan_amendment_review(
    repository: Path,
    amendment_sha256: str,
    amendment_fingerprint: str,
) -> None:
    path = repository / PLAN_AMENDMENT_REVIEW_RELATIVE_PATH
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_PLAN_AMENDMENT_REVIEW_SHA256:
        raise ValueError("Intraday Exposed 002 plan-amendment-review SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 plan amendment review")
    stored_fingerprint = _text(value, "review_fingerprint")
    unsigned = dict(value)
    del unsigned["review_fingerprint"]
    reviewed_base = _mapping(value.get("reviewed_base_plan"), "reviewed base plan")
    reviewed_amendment = _mapping(value.get("reviewed_amendment"), "reviewed amendment")
    reviewed_disposition = _mapping(
        value.get("reviewed_acquisition_disposition"), "reviewed acquisition disposition"
    )
    verification = _mapping(value.get("verification"), "amendment-review verification")
    raw_answers = value.get("answers")
    if not isinstance(raw_answers, list):
        raise ValueError("Intraday Exposed 002 plan amendment review differs")
    answers = tuple(_mapping(item, "amendment-review answer") for item in raw_answers)
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_PLAN_AMENDMENT_REVIEW_FINGERPRINT
        or value.get("schema_version")
        != "intraday-exposed-002-plan-amendment-independent-review-v2"
        or value.get("review_id") != "intraday-exposed-002-plan-amendment-independent-review-v2"
        or value.get("program_id") != PLAN_ID
        or value.get("status") != "passed-before-data-binding-or-strategy-results"
        or value.get("verdict") != "pass"
        or value.get("findings") != []
        or value.get("authority") != _AMENDMENT_AUTHORITY
        or reviewed_base
        != {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLAN_SHA256,
            "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
            "review_path": PLAN_REVIEW_RELATIVE_PATH.as_posix(),
            "review_sha256": REVIEWED_PLAN_REVIEW_SHA256,
            "review_fingerprint": REVIEWED_PLAN_REVIEW_FINGERPRINT,
        }
        or reviewed_amendment
        != {
            "path": PLAN_AMENDMENT_RELATIVE_PATH.as_posix(),
            "sha256": amendment_sha256,
            "amendment_fingerprint": amendment_fingerprint,
        }
        or reviewed_disposition
        != {
            "path": MAY_ACQUISITION_DISPOSITION_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_MAY_ACQUISITION_DISPOSITION_SHA256,
            "disposition_fingerprint": REVIEWED_MAY_ACQUISITION_DISPOSITION_FINGERPRINT,
        }
        or {answer.get("control") for answer in answers}
        != {
            "pre-result-v1-closure",
            "complete-pre-june-raw-evidence",
            "exact-normalized-and-manifest-range",
            "unchanged-strategy-and-program-controls",
            "june-v3-and-result-exclusion",
            "identity-and-authority",
        }
        or any(answer.get("answer") != "pass" for answer in answers)
        or verification.get("amendment_sha256_revalidated") is not True
        or verification.get("amendment_fingerprint_revalidated") is not True
        or verification.get("disposition_sha256_revalidated") is not True
        or verification.get("disposition_fingerprint_revalidated") is not True
        or verification.get("cross_artifact_consistency_passed") is not True
        or verification.get("exact_staged_byte_review") is not True
        or verification.get("market_data_artifacts_opened") is not False
    ):
        raise ValueError("Intraday Exposed 002 plan amendment review differs")


def _load_data_binding(
    repository: Path,
    base_payload: Mapping[str, Any],
    amendment_payload: Mapping[str, Any],
    amendment_sha256: str,
    amendment_fingerprint: str,
) -> tuple[Path, str, str, Mapping[str, Any]]:
    path = repository / DATA_BINDING_RELATIVE_PATH
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != REVIEWED_DATA_BINDING_SHA256:
        raise ValueError("Intraday Exposed 002 data-binding SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 data binding")
    stored_fingerprint = _text(value, "binding_fingerprint")
    unsigned = dict(value)
    del unsigned["binding_fingerprint"]
    dependencies = _mapping(value.get("frozen_dependencies"), "binding dependencies")
    may_dataset = _mapping(value.get("may_dataset"), "bound May dataset")
    validation = _mapping(value.get("validation"), "binding validation")
    gates = _mapping(value.get("execution_gates"), "binding execution gates")
    replacement = _mapping(
        amendment_payload.get("replacement_data_contract"), "amended data contract"
    )
    bound = _mapping(replacement.get("bound_acquisition"), "amended bound acquisition")
    raw_transport = _mapping(replacement.get("raw_transport"), "amended raw transport")
    normalized = _mapping(replacement.get("normalized_parquet"), "amended normalized Parquet")
    manifest = _mapping(replacement.get("manifest"), "amended manifest")
    base_data = _mapping(base_payload.get("data"), "base plan data")
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_DATA_BINDING_FINGERPRINT
        or value.get("schema_version") != "intraday-exposed-002-data-binding-v1"
        or value.get("binding_id") != "intraday-exposed-002-data-binding-v1"
        or value.get("program_id") != PLAN_ID
        or value.get("status") != "frozen-after-amendment-merge-before-runner-or-strategy-results"
        or value.get("binding_main") != _DATA_BINDING_STARTING_MAIN
        or value.get("selection_basis")
        != (
            "Bind the only artifact published by the exact post-plan GET. No price value, "
            "strategy result, alternate acquisition, or existing May-June artifact informed "
            "the selection."
        )
        or value.get("authority") != _DATA_BINDING_AUTHORITY
        or dependencies
        != {
            "base_plan": {
                "path": PLAN_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_PLAN_SHA256,
                "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
                "review_path": PLAN_REVIEW_RELATIVE_PATH.as_posix(),
                "review_sha256": REVIEWED_PLAN_REVIEW_SHA256,
                "review_fingerprint": REVIEWED_PLAN_REVIEW_FINGERPRINT,
            },
            "plan_amendment": {
                "path": PLAN_AMENDMENT_RELATIVE_PATH.as_posix(),
                "sha256": amendment_sha256,
                "amendment_fingerprint": amendment_fingerprint,
                "review_path": PLAN_AMENDMENT_REVIEW_RELATIVE_PATH.as_posix(),
                "review_sha256": REVIEWED_PLAN_AMENDMENT_REVIEW_SHA256,
                "review_fingerprint": REVIEWED_PLAN_AMENDMENT_REVIEW_FINGERPRINT,
            },
            "acquisition_disposition": {
                "path": MAY_ACQUISITION_DISPOSITION_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_MAY_ACQUISITION_DISPOSITION_SHA256,
                "disposition_fingerprint": REVIEWED_MAY_ACQUISITION_DISPOSITION_FINGERPRINT,
            },
        }
        or may_dataset
        != {
            "dataset_id": bound.get("dataset_id"),
            "fingerprint": bound.get("fingerprint"),
            "raw_fingerprint": bound.get("raw_fingerprint"),
            "raw_sha256": bound.get("raw_sha256"),
            "manifest_sha256": bound.get("manifest_sha256"),
            "bars_sha256": bound.get("bars_sha256"),
            "provider": manifest.get("provider"),
            "feed": manifest.get("feed"),
            "symbols": ["SPY", "QQQ"],
            "timeframe": manifest.get("timeframe"),
            "adjustment_policy": base_data.get("adjustment_policy"),
            "calendar_policy": base_data.get("calendar_policy"),
            "timestamp_policy": base_data.get("timestamp_policy"),
            "universe_id": base_data.get("universe_id"),
            "universe_fingerprint": base_data.get("universe_fingerprint"),
            "requested_start": manifest.get("requested_start"),
            "requested_end": manifest.get("requested_end"),
            "actual_start": normalized.get("actual_start"),
            "actual_end": normalized.get("actual_end"),
            "raw_start": raw_transport.get("actual_start"),
            "raw_end": raw_transport.get("actual_end"),
            "raw_record_count": raw_transport.get("record_count"),
            "raw_outside_regular_grid_count": raw_transport.get("outside_regular_grid_count"),
            "session_count": normalized.get("session_count"),
            "bar_count": normalized.get("bar_count"),
            "retrieval_timestamp": "2026-08-21T00:51:06.432445Z",
            "parent_dataset_id": None,
            "acquisition_main": bound.get("acquisition_main"),
            "contains_june_market_timestamp": False,
            "physically_bounded_before_june": True,
        }
        or validation
        != {
            "full_dataset_validation_performed_after_amendment_merge": True,
            "dataset_service_validation_passed": True,
            "catalog_matches_manifest": True,
            "identity_matches_manifest": True,
            "raw_artifact_matches": True,
            "raw_sha256_revalidated": True,
            "manifest_sha256_revalidated": True,
            "bars_sha256_revalidated": True,
            "normalized_fingerprint_revalidated": True,
            "raw_fingerprint_revalidated": True,
            "missing_interval_count": 0,
            "duplicate_interval_count": 0,
            "conflict_count": 0,
            "quarantined_record_count": 0,
            "raw_contains_june_market_timestamp": False,
            "normalized_contains_june_market_timestamp": False,
            "existing_may_june_artifact_accessed": False,
            "strategy_result_access": False,
            "v3_data_access": False,
            "paper_or_broker_state_access": False,
            "strategic_allocation_21_access": False,
        }
        or gates
        != {
            "data_binding_independent_review_required": True,
            "data_binding_merge_required": True,
            "runner_implementation_and_merge_required": True,
            "strategy_execution_allowed_now": False,
        }
    ):
        raise ValueError("Intraday Exposed 002 data binding differs")
    return path, sha256, stored_fingerprint, value


def _verify_data_binding_review(
    repository: Path,
    binding_sha256: str,
    binding_fingerprint: str,
) -> None:
    path = repository / DATA_BINDING_REVIEW_RELATIVE_PATH
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_DATA_BINDING_REVIEW_SHA256:
        raise ValueError("Intraday Exposed 002 data-binding-review SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 data binding review")
    stored_fingerprint = _text(value, "review_fingerprint")
    unsigned = dict(value)
    del unsigned["review_fingerprint"]
    reviewed_binding = _mapping(value.get("reviewed_binding"), "reviewed data binding")
    reviewed_amendment = _mapping(value.get("reviewed_amendment"), "binding-reviewed amendment")
    verification = _mapping(value.get("verification"), "data-binding-review verification")
    raw_answers = value.get("answers")
    if not isinstance(raw_answers, list):
        raise ValueError("Intraday Exposed 002 data binding review differs")
    answers = tuple(_mapping(item, "data-binding-review answer") for item in raw_answers)
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_DATA_BINDING_REVIEW_FINGERPRINT
        or value.get("schema_version") != "intraday-exposed-002-data-binding-independent-review-v1"
        or value.get("review_id") != "intraday-exposed-002-data-binding-independent-review-v1"
        or value.get("program_id") != PLAN_ID
        or value.get("status") != "passed-before-runner-or-strategy-results"
        or value.get("verdict") != "pass"
        or value.get("findings") != []
        or value.get("authority") != _DATA_BINDING_AUTHORITY
        or reviewed_binding
        != {
            "path": DATA_BINDING_RELATIVE_PATH.as_posix(),
            "sha256": binding_sha256,
            "binding_fingerprint": binding_fingerprint,
        }
        or reviewed_amendment
        != {
            "path": PLAN_AMENDMENT_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLAN_AMENDMENT_SHA256,
            "amendment_fingerprint": REVIEWED_PLAN_AMENDMENT_FINGERPRINT,
            "review_path": PLAN_AMENDMENT_REVIEW_RELATIVE_PATH.as_posix(),
            "review_sha256": REVIEWED_PLAN_AMENDMENT_REVIEW_SHA256,
            "review_fingerprint": REVIEWED_PLAN_AMENDMENT_REVIEW_FINGERPRINT,
        }
        or {answer.get("control") for answer in answers}
        != {
            "exact-reviewed-dependency-chain",
            "catalog-manifest-and-content-identity",
            "complete-pre-june-raw-evidence",
            "exact-normalized-may-grid",
            "prospective-single-artifact-selection",
            "remaining-gates-and-authority",
        }
        or any(answer.get("answer") != "pass" for answer in answers)
        or verification.get("binding_sha256_revalidated") is not True
        or verification.get("binding_fingerprint_revalidated") is not True
        or verification.get("dependency_sha256_values_revalidated") is not True
        or verification.get("dataset_service_validation_passed") is not True
        or verification.get("catalog_matches_stored_manifest") is not True
        or verification.get("derived_dataset_id_matches") is not True
        or verification.get("raw_sha256_revalidated") is not True
        or verification.get("bars_sha256_revalidated") is not True
        or verification.get("manifest_sha256_revalidated") is not True
        or verification.get("raw_fingerprint_revalidated") is not True
        or verification.get("normalized_fingerprint_revalidated") is not True
        or verification.get("all_permitted_artifact_timestamps_before_june") is not True
        or verification.get("exact_staged_byte_review") is not True
        or verification.get("opened_dataset_ids")
        != ["4afa60f29ea266ec8b60be9d9600132f8cff4207e846443c65afd3bb5c497a19"]
        or verification.get("other_dataset_artifacts_opened") is not False
        or verification.get("prices_printed") is not False
    ):
        raise ValueError("Intraday Exposed 002 data binding review differs")


def _verify_artifact(
    repository: Path,
    binding: Mapping[str, Any],
    fingerprint_key: str,
    expected_fingerprint: str,
) -> Mapping[str, Any]:
    path = repository / _text(binding, "path")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _text(binding, "sha256"):
        raise ValueError("Intraday Exposed 002 dependency SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 dependency")
    stored_fingerprint = _text(value, fingerprint_key)
    unsigned = dict(value)
    del unsigned[fingerprint_key]
    if (
        stored_fingerprint != expected_fingerprint
        or binding.get("fingerprint") != stored_fingerprint
        or fingerprint(unsigned) != stored_fingerprint
    ):
        raise ValueError("Intraday Exposed 002 dependency fingerprint differs")
    return value


def _periods(payload: Mapping[str, Any]) -> tuple[Exposed002Period, ...]:
    chronology = _mapping(payload.get("chronology"), "chronology")
    values = [_mapping(chronology.get("discovery"), "discovery")]
    walk_forward = chronology.get("walk_forward")
    if not isinstance(walk_forward, list) or len(walk_forward) != 4:
        raise ValueError("Intraday Exposed 002 walk-forward periods differ")
    values.extend(_mapping(value, "walk-forward period") for value in walk_forward)
    periods = tuple(_period(value) for value in values)
    if len({period.period_id for period in periods}) != len(periods) or any(
        left.evaluation_end >= right.evaluation_start for left, right in itertools.pairwise(periods)
    ):
        raise ValueError("Intraday Exposed 002 periods overlap or differ")
    return periods


def _period(value: Mapping[str, Any]) -> Exposed002Period:
    period = Exposed002Period(
        _text(value, "period_id"),
        _timestamp(value.get("context_start"), "context start"),
        _timestamp(value.get("evaluation_start"), "evaluation start"),
        _timestamp(value.get("evaluation_end"), "evaluation end"),
        _positive_int(value.get("session_count"), "session count"),
    )
    if (
        period.context_start > period.evaluation_start
        or period.evaluation_end > _LATEST_PERMITTED_BAR
    ):
        raise ValueError("Intraday Exposed 002 period exceeds its permitted range")
    bars = expected_bar_timestamps(
        period.evaluation_start,
        period.evaluation_end,
        Timeframe.FIVE_MINUTES,
    )
    sessions = expected_sessions(period.evaluation_start, period.evaluation_end)
    if (
        not bars
        or bars[0] != period.evaluation_start
        or bars[-1] != period.evaluation_end
        or len(sessions) != period.session_count
    ):
        raise ValueError("Intraday Exposed 002 period calendar differs")
    return period


def _configurations(payload: Mapping[str, Any]) -> tuple[Exposed002Configuration, ...]:
    contract = _mapping(payload.get("configuration_contract"), "configuration contract")
    families = contract.get("families")
    if not isinstance(families, list) or len(families) != len(_FAMILY_IDS):
        raise ValueError("Intraday Exposed 002 families differ")
    result: list[Exposed002Configuration] = []
    for expected_ordinal, (expected_id, raw_family) in enumerate(
        zip(_FAMILY_IDS, families, strict=True), 1
    ):
        family = _mapping(raw_family, "strategy family")
        ordinal = _positive_int(family.get("family_ordinal"), "family ordinal")
        family_id = _text(family, "family_id")
        axes = family.get("axes")
        fixed = _mapping(family.get("fixed_parameters"), "fixed parameters")
        if ordinal != expected_ordinal or family_id != expected_id:
            raise ValueError("Intraday Exposed 002 family identity differs")
        if not isinstance(axes, list) or len(axes) != 2:
            raise ValueError("Intraday Exposed 002 family axes differ")
        parsed_axes = tuple(_axis(value) for value in axes)
        if len({name for name, _values in parsed_axes}) != 2 or set(fixed) & {
            name for name, _values in parsed_axes
        }:
            raise ValueError("Intraday Exposed 002 family parameters collide")
        axis_values = tuple(values for _name, values in parsed_axes)
        if len(axis_values[0]) * len(axis_values[1]) != 6:
            raise ValueError("Intraday Exposed 002 family must contain six parents")
        for first_index, second_index in itertools.product(
            range(len(axis_values[0])), range(len(axis_values[1]))
        ):
            candidate_id = _candidate_id(ordinal, first_index, second_index)
            parameters: dict[str, object] = dict(fixed)
            parameters[parsed_axes[0][0]] = axis_values[0][first_index]
            parameters[parsed_axes[1][0]] = axis_values[1][second_index]
            neighbors: list[str] = []
            for axis_index, current in enumerate((first_index, second_index)):
                for neighbor in (current - 1, current + 1):
                    if 0 <= neighbor < len(axis_values[axis_index]):
                        indices = [first_index, second_index]
                        indices[axis_index] = neighbor
                        neighbors.append(_candidate_id(ordinal, indices[0], indices[1]))
            if len(neighbors) < 2:
                raise ValueError("Intraday Exposed 002 parameter neighborhood is incomplete")
            result.append(
                Exposed002Configuration(
                    candidate_id,
                    family_id,
                    ordinal,
                    parameters,
                    tuple(sorted(neighbors)),
                )
            )
    configurations = tuple(result)
    if (
        len(configurations) != 60
        or len({item.candidate_id for item in configurations}) != 60
        or contract.get("parent_configuration_count") != 60
        or _positive_int(
            contract.get("maximum_parent_configurations"), "maximum parent configurations"
        )
        != 800
        or contract.get("maximum_free_parameters_per_family") != 2
    ):
        raise ValueError("Intraday Exposed 002 parent budget differs")
    return configurations


def _axis(value: object) -> tuple[str, tuple[object, ...]]:
    axis = _mapping(value, "parameter axis")
    name = _text(axis, "name")
    values = axis.get("values")
    if not isinstance(values, list) or len(values) not in {2, 3}:
        raise ValueError("Intraday Exposed 002 parameter axis differs")
    if any(isinstance(item, bool) or not isinstance(item, str | int) for item in values):
        raise ValueError("Intraday Exposed 002 parameter value differs")
    if len({json.dumps(item, sort_keys=True) for item in values}) != len(values):
        raise ValueError("Intraday Exposed 002 parameter values repeat")
    return name, tuple(values)


def _candidate_id(ordinal: int, first_index: int, second_index: int) -> str:
    return f"ie002-f{ordinal:02d}-a{first_index + 1:02d}-b{second_index + 1:02d}"


def _verify_data_boundary(
    payload: Mapping[str, Any], periods: tuple[Exposed002Period, ...]
) -> None:
    data = _mapping(payload.get("data"), "data")
    bindings = data.get("dataset_bindings")
    if not isinstance(bindings, list) or len(bindings) != 3:
        raise ValueError("Intraday Exposed 002 dataset bindings differ")
    allowed_ranges = tuple(
        (
            _timestamp(
                _mapping(binding, "dataset binding").get("allowed_read_start"),
                "allowed start",
            ),
            _timestamp(
                _mapping(binding, "dataset binding").get("allowed_read_end"),
                "allowed end",
            ),
        )
        for binding in bindings
    )
    may = _mapping(data.get("may_only_acquisition"), "May-only acquisition")
    may_start = _timestamp(may.get("requested_start"), "May requested start")
    may_end = _timestamp(may.get("requested_end"), "May requested end")
    expected_may_bars = expected_bar_timestamps(may_start, may_end, Timeframe.FIVE_MINUTES)
    expected_may_sessions = expected_sessions(may_start, may_end)
    required_binding = _mapping(data.get("required_data_binding"), "required data binding")
    if (
        data.get("symbols") != ["QQQ", "SPY"]
        or data.get("timeframe") != "5m"
        or data.get("provider") != "alpaca-historical-v2"
        or data.get("feed") != "iex"
        or allowed_ranges != _EXISTING_DATA_RANGES
        or max(end for _start, end in allowed_ranges) != _PRE_MAY_DATA_END
        or any(period.evaluation_end > _PRE_MAY_DATA_END for period in periods[:-1])
        or periods[-1].evaluation_start != _MAY_START
        or periods[-1].evaluation_end != _LATEST_PERMITTED_BAR
        or may.get("status") != "pending-until-plan-merges"
        or may.get("provider") != "alpaca-historical-v2"
        or may.get("http_method") != "GET"
        or may.get("feed") != "iex"
        or may.get("fallback_allowed") is not False
        or may.get("symbols") != ["QQQ", "SPY"]
        or may.get("timeframe") != "5m"
        or may_start != _MAY_START
        or may_end != _LATEST_PERMITTED_BAR
        or may.get("expected_session_count") != len(expected_may_sessions)
        or may.get("expected_bar_count") != len(expected_may_bars) * 2
        or may.get("adjustment_policy") != "provider-adjusted-all-v1"
        or may.get("universe_id") != "liquid-etfs-intraday-5m-v1"
        or may.get("universe_fingerprint")
        != "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
        or may.get("existing_artifact_derivation_allowed") is not False
        or required_binding.get("path")
        != "config/research/intraday-exposed-002-data-binding-v1.json"
        or required_binding.get("status")
        != "must-be-frozen-and-independently-reviewed-before-strategy-results"
        or required_binding.get("required_fields") != _DATA_BINDING_FIELDS
        or data.get("all_runtime_datasets_must_be_physically_bounded_before_june") is not True
        or data.get("generic_filtered_read_of_artifact_containing_june") is not False
        or data.get("full_dataset_validation_during_campaign") is not True
        or data.get("acquire_one_minute_data") is not False
        or _timestamp(data.get("latest_permitted_bar"), "latest permitted bar")
        != _LATEST_PERMITTED_BAR
    ):
        raise ValueError("Intraday Exposed 002 data boundary differs")


def _verify_screens(payload: Mapping[str, Any]) -> None:
    if _gate_metrics(payload, "discovery_screen", "gates") != _DISCOVERY_METRICS:
        raise ValueError("Intraday Exposed 002 discovery gates differ")
    if _gate_metrics(payload, "walk_forward_screen", "gates") != _WALK_FORWARD_METRICS:
        raise ValueError("Intraday Exposed 002 walk-forward gates differ")
    serious = _mapping(payload.get("serious_candidate_screen"), "serious screen")
    if _gate_metrics(serious, None, "stress_gates") != _STRESS_METRICS:
        raise ValueError("Intraday Exposed 002 stress gates differ")
    if _gate_metrics(serious, None, "neighbor_gates") != {
        "positive_neighbor_fraction",
        "median_neighbor_normal_profit_retention",
    }:
        raise ValueError("Intraday Exposed 002 neighbor gates differ")
    discovery = _mapping(payload.get("discovery_screen"), "discovery screen")
    walk_forward = _mapping(payload.get("walk_forward_screen"), "walk-forward screen")
    cohort = _mapping(payload.get("final_cohort"), "final cohort")
    if (
        discovery.get("run_all_parents_before_screening") is not True
        or discovery.get("walk_forward_cap") != 30
        or walk_forward.get("serious_candidate_cap") != 15
        or cohort.get("maximum_size") != 5
        or cohort.get("maximum_per_family") != 1
    ):
        raise ValueError("Intraday Exposed 002 selection caps differ")


def _gate_metrics(payload: Mapping[str, Any], section: str | None, key: str) -> set[str]:
    values = _mapping(payload.get(section), section) if section is not None else payload
    gates = values.get(key)
    if not isinstance(gates, list):
        raise ValueError("Intraday Exposed 002 gates must be a list")
    metrics: list[str] = []
    for value in gates:
        gate = _mapping(value, "gate")
        metric = _text(gate, "metric")
        if (
            gate.get("comparison") not in {">", ">=", "<=", "="}
            or isinstance(gate.get("threshold"), bool)
            or not isinstance(gate.get("threshold"), str | int)
        ):
            raise ValueError("Intraday Exposed 002 gate differs")
        metrics.append(metric)
    if len(metrics) != len(set(metrics)):
        raise ValueError("Intraday Exposed 002 gate metrics repeat")
    return set(metrics)


def _verify_controlled_boundary(payload: Mapping[str, Any]) -> None:
    controlled = _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
    if (
        controlled.get("range_status") != "ineligible"
        or controlled.get("june_read") is not False
        or controlled.get("substitute_range") is not False
        or controlled.get("controlled_plan_creation") is not False
    ):
        raise ValueError("Intraday Exposed 002 controlled boundary differs")


def _mapping(value: object, label: str | None) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label or 'value'} must be an object")
    return value


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be text")
    return item


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be a UTC timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    offset = result.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{label} must be a UTC timestamp")
    return result
