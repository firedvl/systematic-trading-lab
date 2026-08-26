"""Strict loader for the frozen Program 002 research contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .domain import Symbol
from .fingerprints import fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-001"
PLAN_RELATIVE_PATH = Path(
    "config/research/cross-sectional-sector-etf-program-002-plan-proposal-v1.json"
)
ACQUISITION_PLAN_RELATIVE_PATH = Path(
    "config/research/cross-sectional-sector-etf-program-002-data-acquisition-plan-proposal-v1.json"
)
ACQUISITION_CONTROL_AMENDMENT_RELATIVE_PATH = Path(
    "config/research/program-002-acquisition-control-amendment-v2.json"
)
PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH = Path(
    "config/research/program-002-provider-contract-evidence-v1.json"
)
ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH = Path(
    "config/research/program-002-account-isolation-proof-v1.json"
)
ACCOUNT_ISOLATION_PROOF_REVIEW_RELATIVE_PATH = Path(
    "config/research/program-002-account-isolation-proof-independent-review-v1.json"
)
ACQUISITION_AUTHORITY_V2_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-v2.json"
)
ACQUISITION_AUTHORITY_REVIEW_V1_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-independent-review-v1.json"
)
ACQUISITION_RUNTIME_FAILURE_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-runtime-failure-v1.json"
)
ACQUISITION_AUTHORITY_V3_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-v3.json"
)
ACQUISITION_AUTHORITY_V3_REVIEW_FAILURE_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-v3-review-failure-v1.json"
)
ACQUISITION_AUTHORITY_V4_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-v4.json"
)
ACQUISITION_AUTHORITY_REVIEW_V2_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-independent-review-v2.json"
)
ACQUISITION_PAGINATION_FAILURE_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-pagination-failure-v1.json"
)
ACQUISITION_PAGINATION_AMENDMENT_RELATIVE_PATH = Path(
    "config/research/program-002-acquisition-pagination-amendment-v1.json"
)
ACQUISITION_PAGINATION_AMENDMENT_REVIEW_RELATIVE_PATH = Path(
    "config/research/program-002-acquisition-pagination-amendment-independent-review-v1.json"
)
ACQUISITION_AUTHORITY_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-v5.json"
)
ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH = Path(
    "config/research/program-002-exposed-acquisition-authority-independent-review-v3.json"
)
ACQUISITION_CONTROL_REPAIR_REVIEW_RELATIVE_PATH = Path(
    "config/research/program-002-acquisition-control-repair-independent-review-v1.json"
)
COST_MODEL_RELATIVE_PATH = Path("config/research/intraday-execution-cost-model-001-v1.json")
UNIVERSE_RELATIVE_PATH = Path("config/research/multi-hour-sector-etfs-v1.json")
AUTHORITY_RELATIVE_PATH = Path(
    "config/research/program-002-implementation-acquisition-authority-v1.json"
)
IMPLEMENTATION_PLAN_RELATIVE_PATH = Path(
    "docs/research-campaigns/multi-hour-sector-etf-research-001-implementation-plan.md"
)
PLANNING_REVIEW_RELATIVE_PATH = Path(
    "config/research/cross-sectional-sector-etf-program-002-plan-independent-review-v1.json"
)
REVIEWED_AUTHORITY_SHA256 = "c1fb084b0ac36f7270b56066e499258f18c38adb393b7b597b3d4e1a593e6ca3"
REVIEWED_AUTHORIZATION_PACKET_SHA256 = (
    "8314190d0525e1ff4bd479bc9c1f455f7b40c9e295bc0ccdc8c5d7fcd4a97785"
)
REVIEWED_PLAN_SHA256 = "2872d4d3301df0a85e1a5a2eba6e3ee533ee5573971121e99840041e7c8d2173"
REVIEWED_PLAN_FINGERPRINT = "701dc67ea2da1e45d235f4247724b2bc8eb62853561c2400c17a668342c6b81e"
REVIEWED_ACQUISITION_PLAN_SHA256 = (
    "26c768f422e63e9f00e6adc88be2d57f5c6447972a9de1fa4873ab2826556aae"
)
REVIEWED_ACQUISITION_CONTROL_AMENDMENT_SHA256 = (
    "ecabaf6a46ea24cd88dc7e62aa3e27d78180f57aff7af671840a092747e7b5b5"
)
REVIEWED_ACQUISITION_CONTROL_AMENDMENT_FINGERPRINT = (
    "6db1a382621c146f7d389c1997c5dc66c73471f530fcf1e89e1ec1f01eb9685a"
)
REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256 = (
    "86a9740a1ecd74f3152e470b9d2fa1c2f759c3a1e9b19b30b54c2ae7b94d0bf2"
)
REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT = (
    "5d11a9fb2cbf35f48f857de88737c5e67a04348d9d696f98367039e694f925d6"
)
REVIEWED_ACCOUNT_ISOLATION_PROOF_SHA256 = (
    "21800879cb4825dd147214e7a5720fb6d6978b00a887efd0a7789baa4a8d94e7"
)
REVIEWED_ACCOUNT_ISOLATION_PROOF_FINGERPRINT = (
    "a8a4063837a93d866aa1d0ca4bd3ecdeb6e196fd810efea9104f125588923ba7"
)
REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_SHA256 = (
    "ac1a83d2f50424cd1a88e93d9e6cbbaabedc2802ece390a0d1f0b96da5d697c2"
)
REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_FINGERPRINT = (
    "2776ada38e5912f7631bf694fa645854c8cbc0a8539a01ef4fe2472a56386478"
)
REVIEWED_ACCOUNT_ISOLATION_PROOF_COMMIT = "00298a0c089d5e5912f2d3d622ffa2ea257c2c14"
REVIEWED_ACQUISITION_AUTHORITY_V2_SHA256 = (
    "5543f427e9b7058bd8ed827af476eb48138eb4199788ca0437c9b4c8b70b5262"
)
REVIEWED_ACQUISITION_AUTHORITY_V2_FINGERPRINT = (
    "5e734986a9cdb9058375f95a1457c00ffa1329f1bf7e9245834af43f04c807f4"
)
REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V1_SHA256 = (
    "20c254ad448d9c036a78a59eedf3d04b642775b01d06f4a52a4a09689f582d2c"
)
REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V1_FINGERPRINT = (
    "249fa690a3e4a0bb313561895f91547b1a61264f8b46dc37bafddb9b7fd86f07"
)
REVIEWED_ACQUISITION_RUNTIME_FAILURE_SHA256 = (
    "af17ee7d34317d33db5be7672f2d490c03401e35c0aee43b040519a7fea7df0e"
)
REVIEWED_ACQUISITION_RUNTIME_FAILURE_FINGERPRINT = (
    "07418cd02962e6284df3447a01df4c871c78f9cf476ae7d02935fe1c7fe9828d"
)
REVIEWED_ACQUISITION_AUTHORITY_V3_SHA256 = (
    "d09b12048c9da25cb360781d5b17aa8c614b4670c6e921f6933b89e67bb4ac72"
)
REVIEWED_ACQUISITION_AUTHORITY_V3_FINGERPRINT = (
    "4f4c5275f9dfc2d019fc57829c87caa643800d8581bbb065c49a15f39369db34"
)
REVIEWED_ACQUISITION_AUTHORITY_V3_REVIEW_FAILURE_SHA256 = (
    "1aa0efdcd2bd95a8adde83e75a3116cb0473e5c99cb0d8a4b25a8e3f717c9da8"
)
REVIEWED_ACQUISITION_AUTHORITY_V3_REVIEW_FAILURE_FINGERPRINT = (
    "3e31ffdcd8ec590297c79861d29e23e824f18efd21063b3c60f502ba0f1f1d0d"
)
REVIEWED_ACQUISITION_AUTHORITY_V4_SHA256 = (
    "4c2f707c1c96a5671422faee41a1b6dcc3e78f42573519c7df38b3e9b1acba0a"
)
REVIEWED_ACQUISITION_AUTHORITY_V4_FINGERPRINT = (
    "a9eecc8ffbf2c91fdb66418b73ce920595035ca7b423a1acf2ad7cc0d5f1f8a9"
)
REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V2_SHA256 = (
    "b47d49774af2e548203a9e125b02cd408b0dcd55037d0ab850cd1402df4c5787"
)
REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V2_FINGERPRINT = (
    "baa1df63bd96ed2a8c0c6af0a617d17955defb9b521ddeea4591838df15724ac"
)
REVIEWED_ACQUISITION_PAGINATION_FAILURE_SHA256 = (
    "b0656fb36c2ca5ecd97034a37e2630bf363765d5e01711a8092cd76f3235babc"
)
REVIEWED_ACQUISITION_PAGINATION_FAILURE_FINGERPRINT = (
    "2537863a4f3f8215f573ea028949c5ef49c802ade2d3bcf2878af8bdf0607d1a"
)
REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_SHA256 = (
    "c6f709f2f9388929823ac780e82c8f8eda8c022cd5c9a01c42e550a570071840"
)
REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_FINGERPRINT = (
    "986a5aeab8b7aa351b15882dcd14271e52b6e1901c7be362a158809d23aed73c"
)
REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_REVIEW_SHA256 = (
    "7969a04cab7206e8b1f8a2db0850768c4abc2d8573b93633c9093636418424ea"
)
REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_REVIEW_FINGERPRINT = (
    "11c6c8fd556a3d61893164b89f75653d6ecbd566d28b173bf2c2af9580414c60"
)
REVIEWED_ACQUISITION_PAGINATION_PROPOSAL_COMMIT = "63470f4f64d73a456dc1f1a1ac6ceb09354409fc"
REVIEWED_ACQUISITION_CONTROL_REPAIR_REVIEW_SHA256 = (
    "44ee39877e0135092f278b12aa224fbd578a08a59a05dcdd4fd0c1cbaf8feb48"
)
REVIEWED_ACQUISITION_CONTROL_REPAIR_REVIEW_FINGERPRINT = (
    "ca733b0f015715a18e123872cd15a34a1bb743718d487da87a3b3ae4e2447c74"
)
REVIEWED_COST_MODEL_SHA256 = "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af"
REVIEWED_COST_MODEL_FINGERPRINT = "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4"
REVIEWED_UNIVERSE_SHA256 = "8f07f73fd93f9432501d579e43616e1d9a09d6db77c347a6bed4151f2210c312"
REVIEWED_UNIVERSE_FINGERPRINT = "ef23e533aa7a91262200bd7a77a65f9b6d8b4d473573850c33ef014701177790"
REVIEWED_IMPLEMENTATION_PLAN_SHA256 = (
    "aebfea81a2c8a4110d369dbd23d12e0ff79a661fc8f6187df0f27939abdfede5"
)
REVIEWED_PLANNING_REVIEW_SHA256 = "b5023c90a7d748a7c8ac42609bad6d1c394150bc914c51b8b65c73e3d80c17e6"
REVIEWED_PLANNING_REVIEW_FINGERPRINT = (
    "55e30955789981a4eca129856322207ceb05fa9aebccb1101d892dd92f7a5d33"
)

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
_RANKING_SYMBOLS = tuple(
    Symbol(value)
    for value in (
        "IWM",
        "MDY",
        "XLB",
        "XLE",
        "XLF",
        "XLI",
        "XLK",
        "XLP",
        "XLRE",
        "XLU",
        "XLV",
        "XLY",
    )
)
_SPY = Symbol("SPY")
_NUMERIC_POLICY = (
    "Use Decimal price and return arithmetic and exact integer volumes. "
    "No floating-point ranking key is permitted."
)

ACQUISITION_SOURCE_PATHS = (
    "src/systematic_trading_lab/__init__.py",
    "src/systematic_trading_lab/calendar.py",
    "src/systematic_trading_lab/catalog.py",
    "src/systematic_trading_lab/config.py",
    "src/systematic_trading_lab/datasets.py",
    "src/systematic_trading_lab/domain.py",
    "src/systematic_trading_lab/fingerprints.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_plan.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_features.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_engine.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_synthetic.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_runner.py",
    "src/systematic_trading_lab/program_002_acquisition.py",
    "src/systematic_trading_lab/program_002_acquisition_cli.py",
    "src/systematic_trading_lab/program_002_account_isolation.py",
    "src/systematic_trading_lab/program_002_credentials.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_launch_control.py",
    "src/systematic_trading_lab/intraday_execution_cost_model.py",
    "src/systematic_trading_lab/parquet.py",
    "src/systematic_trading_lab/providers.py",
    "src/systematic_trading_lab/storage.py",
    "src/systematic_trading_lab/universe.py",
    "src/systematic_trading_lab/validation.py",
    "pyproject.toml",
    "uv.lock",
)


@dataclass(frozen=True)
class Program002Configuration:
    configuration_id: str
    family_id: str
    strategy_id: str
    lookback_30m_bars: int
    hold_30m_bars: int
    immediate_neighbors: tuple[str, str]


@dataclass(frozen=True)
class Program002Authority:
    path: Path
    sha256: str
    authority_id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class Program002Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    universe_path: Path
    universe_sha256: str
    universe_fingerprint: str
    ranking_symbols: tuple[Symbol, ...]
    context_symbol: Symbol
    configurations: Mapping[str, Program002Configuration]
    payload: Mapping[str, Any]
    universe_payload: Mapping[str, Any]
    authority: Program002Authority

    def __post_init__(self) -> None:
        object.__setattr__(self, "configurations", MappingProxyType(dict(self.configurations)))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "universe_payload", MappingProxyType(dict(self.universe_payload)))


@dataclass(frozen=True)
class Program002AcquisitionPlan:
    path: Path
    sha256: str
    payload: Mapping[str, Any]
    authority: Program002Authority
    control_path: Path
    control_sha256: str
    control_fingerprint: str
    control_payload: Mapping[str, Any]
    provider_contract_evidence_path: Path
    provider_contract_evidence_sha256: str
    provider_contract_evidence_fingerprint: str
    provider_contract_evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "control_payload", MappingProxyType(dict(self.control_payload)))
        object.__setattr__(
            self,
            "provider_contract_evidence",
            MappingProxyType(dict(self.provider_contract_evidence)),
        )


def load_program_002_authority(repository: Path) -> Program002Authority:
    repository = repository.resolve()
    path = repository / AUTHORITY_RELATIVE_PATH
    raw = path.read_bytes()
    _require_sha256(raw, REVIEWED_AUTHORITY_SHA256, "Program 002 authority")
    payload = _load_unique_json(raw, "Program 002 authority")
    _verify_authority(repository, payload)
    return Program002Authority(
        path,
        REVIEWED_AUTHORITY_SHA256,
        "program-002-implementation-acquisition-2026-08-25-v1",
        payload,
    )


def load_program_002_acquisition_authority(repository: Path) -> Program002Authority:
    repository = repository.resolve()
    path = repository / ACQUISITION_AUTHORITY_RELATIVE_PATH
    raw = path.read_bytes()
    payload = _load_unique_json(raw, "Program 002 acquisition authority v5")
    proof_path = repository / ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH
    proof_review_path = repository / ACCOUNT_ISOLATION_PROOF_REVIEW_RELATIVE_PATH
    proof_raw = proof_path.read_bytes()
    proof_review_raw = proof_review_path.read_bytes()
    _require_sha256(
        proof_raw,
        REVIEWED_ACCOUNT_ISOLATION_PROOF_SHA256,
        "Program 002 account-isolation proof",
    )
    _require_sha256(
        proof_review_raw,
        REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_SHA256,
        "Program 002 account-isolation proof review",
    )
    proof = _load_unique_json(proof_raw, "Program 002 account-isolation proof")
    proof_review = _load_unique_json(proof_review_raw, "Program 002 account-isolation proof review")
    _verify_account_isolation_proof(proof)
    _verify_account_isolation_proof_review(proof_review)
    _verify_acquisition_authority_v5(repository, payload, proof)
    return Program002Authority(
        path,
        hashlib.sha256(raw).hexdigest(),
        "program-002-exposed-acquisition-2026-08-26-v5",
        payload,
    )


def load_program_002_acquisition_authority_review(
    repository: Path, authority: Program002Authority
) -> Mapping[str, Any]:
    path = repository.resolve() / ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH
    value = _load_unique_json(path.read_bytes(), "Program 002 acquisition authority review")
    unsigned = dict(value)
    review_fingerprint = unsigned.pop("review_fingerprint", None)
    binding = _mapping(value.get("reviewed_authority"), "reviewed acquisition authority")
    source = _mapping(value.get("reviewed_source"), "reviewed acquisition source")
    review_authority = _mapping(value.get("authority"), "acquisition review authority")
    files = source.get("files")
    if (
        value.get("schema_version")
        != "program-002-exposed-acquisition-authority-independent-review-v3"
        or value.get("program_id") != PROGRAM_ID
        or value.get("status") != "passed-before-market-data-acquisition"
        or value.get("verdict") != "pass"
        or value.get("findings") != []
        or review_fingerprint != fingerprint(unsigned)
        or binding
        != {
            "path": ACQUISITION_AUTHORITY_RELATIVE_PATH.as_posix(),
            "sha256": authority.sha256,
            "fingerprint": authority.payload.get("authority_fingerprint"),
        }
        or source.get("source_commit")
        != _mapping(authority.payload.get("source_binding"), "authority source binding").get(
            "source_commit"
        )
        or not _is_commit(source.get("authority_artifact_commit"))
        or set(source) != {"source_commit", "authority_artifact_commit", "files"}
        or not isinstance(files, list)
        or files != authority.payload.get("source_binding", {}).get("files")
        or set(review_authority) != _AUTHORITY_KEYS
        or any(flag is not False for flag in review_authority.values())
    ):
        raise ValueError("Program 002 acquisition authority review differs")
    return value


def load_program_002_plan(repository: Path) -> Program002Plan:
    repository = repository.resolve()
    authority = load_program_002_authority(repository)
    path = repository / PLAN_RELATIVE_PATH
    universe_path = repository / UNIVERSE_RELATIVE_PATH
    raw = path.read_bytes()
    universe_raw = universe_path.read_bytes()
    _require_sha256(raw, REVIEWED_PLAN_SHA256, "Program 002 plan")
    _require_sha256(universe_raw, REVIEWED_UNIVERSE_SHA256, "Program 002 universe")
    payload = _load_unique_json(raw, "Program 002 plan")
    universe = _load_unique_json(universe_raw, "Program 002 universe")
    _verify_plan_identity(payload)
    _verify_universe(payload, universe)
    configurations = _configurations(payload)
    _verify_contracts(payload, configurations)
    return Program002Plan(
        path,
        REVIEWED_PLAN_SHA256,
        REVIEWED_PLAN_FINGERPRINT,
        universe_path,
        REVIEWED_UNIVERSE_SHA256,
        REVIEWED_UNIVERSE_FINGERPRINT,
        _RANKING_SYMBOLS,
        _SPY,
        configurations,
        payload,
        universe,
        authority,
    )


def load_program_002_account_proof_plan(repository: Path) -> Program002AcquisitionPlan:
    return _load_program_002_acquisition_contract(
        repository.resolve(), load_program_002_authority(repository)
    )


def load_program_002_acquisition_plan(repository: Path) -> Program002AcquisitionPlan:
    repository = repository.resolve()
    authority = load_program_002_acquisition_authority(repository)
    _verify_acquisition_pagination_amendment(repository)
    return _load_program_002_acquisition_contract(repository, authority)


def _load_program_002_acquisition_contract(
    repository: Path, authority: Program002Authority
) -> Program002AcquisitionPlan:
    repository = repository.resolve()
    path = repository / ACQUISITION_PLAN_RELATIVE_PATH
    control_path = repository / ACQUISITION_CONTROL_AMENDMENT_RELATIVE_PATH
    evidence_path = repository / PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH
    raw = path.read_bytes()
    control_raw = control_path.read_bytes()
    evidence_raw = evidence_path.read_bytes()
    _require_sha256(raw, REVIEWED_ACQUISITION_PLAN_SHA256, "Program 002 acquisition plan")
    _require_sha256(
        control_raw,
        REVIEWED_ACQUISITION_CONTROL_AMENDMENT_SHA256,
        "Program 002 acquisition control amendment",
    )
    _require_sha256(
        evidence_raw,
        REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
        "Program 002 provider contract evidence",
    )
    payload = _load_unique_json(raw, "Program 002 acquisition plan")
    control = _load_unique_json(control_raw, "Program 002 acquisition control amendment")
    evidence = _load_unique_json(evidence_raw, "Program 002 provider contract evidence")
    if (
        payload.get("schema_version")
        != "cross-sectional-sector-etf-program-002-data-acquisition-plan-proposal-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "PROPOSED-NOT-AUTHORIZED-FOR-ACQUISITION"
    ):
        raise ValueError("Program 002 acquisition plan identity differs")
    _require_false_authority(payload.get("authority"), "acquisition plan")
    program = _mapping(payload.get("program_plan"), "acquisition program binding")
    universe = _mapping(payload.get("universe"), "acquisition universe binding")
    if program != {
        "path": PLAN_RELATIVE_PATH.as_posix(),
        "status_required": "PROPOSED-NOT-AUTHORIZED",
        "sha256": REVIEWED_PLAN_SHA256,
        "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
    }:
        raise ValueError("Program 002 acquisition plan program binding differs")
    if (
        universe.get("path") != UNIVERSE_RELATIVE_PATH.as_posix()
        or universe.get("sha256") != REVIEWED_UNIVERSE_SHA256
        or universe.get("universe_fingerprint") != REVIEWED_UNIVERSE_FINGERPRINT
    ):
        raise ValueError("Program 002 acquisition plan universe binding differs")
    if any(_mapping(payload.get("launch_control"), "acquisition launch control").values()):
        raise ValueError("Program 002 acquisition proposal unexpectedly grants launch authority")
    _verify_acquisition_control(control, evidence)
    return Program002AcquisitionPlan(
        path,
        REVIEWED_ACQUISITION_PLAN_SHA256,
        payload,
        authority,
        control_path,
        REVIEWED_ACQUISITION_CONTROL_AMENDMENT_SHA256,
        REVIEWED_ACQUISITION_CONTROL_AMENDMENT_FINGERPRINT,
        control,
        evidence_path,
        REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
        REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT,
        evidence,
    )


def _verify_acquisition_control(control: Mapping[str, Any], evidence: Mapping[str, Any]) -> None:
    if (
        control.get("schema_version") != "program-002-acquisition-control-amendment-v2"
        or control.get("program_id") != PROGRAM_ID
        or control.get("status") != "PROSPECTIVE-CONTROL-REPAIR-NOT-AUTHORIZED-FOR-ACQUISITION"
    ):
        raise ValueError("Program 002 acquisition control identity differs")
    unsigned_control = dict(control)
    if (
        unsigned_control.pop("control_fingerprint", None)
        != REVIEWED_ACQUISITION_CONTROL_AMENDMENT_FINGERPRINT
        or fingerprint(unsigned_control) != REVIEWED_ACQUISITION_CONTROL_AMENDMENT_FINGERPRINT
    ):
        raise ValueError("Program 002 acquisition control fingerprint differs")
    unsigned_evidence = dict(evidence)
    if (
        evidence.get("schema_version") != "program-002-provider-contract-evidence-v1"
        or unsigned_evidence.pop("evidence_fingerprint", None)
        != REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT
        or fingerprint(unsigned_evidence) != REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT
    ):
        raise ValueError("Program 002 provider contract evidence differs")
    binding = _mapping(control.get("provider_contract_evidence"), "provider contract binding")
    if binding != {
        "path": PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH.as_posix(),
        "sha256": REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
        "fingerprint": REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT,
    }:
        raise ValueError("Program 002 provider contract binding differs")
    contract = _mapping(control.get("corrected_request_contract"), "corrected request contract")
    if (
        contract.get("start_semantics") != "inclusive"
        or contract.get("end_semantics") != "inclusive"
    ):
        raise ValueError("Program 002 corrected request semantics differ")
    launch = _mapping(control.get("launch_control"), "amended acquisition launch control")
    if launch.get("account_isolation_verification_allowed") is not True or any(
        value is not False
        for key, value in launch.items()
        if key != "account_isolation_verification_allowed"
    ):
        raise ValueError("Program 002 amended launch control differs")
    _require_false_authority(control.get("authority"), "acquisition control amendment")


def _verify_account_isolation_proof(proof: Mapping[str, Any]) -> None:
    unsigned = dict(proof)
    proof_fingerprint = unsigned.pop("proof_fingerprint", None)
    try:
        provider_created_at = datetime.fromisoformat(
            _text(proof, "provider_account_created_at").replace("Z", "+00:00")
        ).astimezone(UTC)
    except ValueError as error:
        raise ValueError("Program 002 proof account timestamp differs") from error
    if (
        proof.get("schema_version") != "program-002-account-isolation-proof-v1"
        or proof.get("program_id") != PROGRAM_ID
        or proof_fingerprint != REVIEWED_ACCOUNT_ISOLATION_PROOF_FINGERPRINT
        or fingerprint(unsigned) != REVIEWED_ACCOUNT_ISOLATION_PROOF_FINGERPRINT
        or proof.get("control_amendment_sha256") != REVIEWED_ACQUISITION_CONTROL_AMENDMENT_SHA256
        or proof.get("environment") not in {"paper", "live"}
        or provider_created_at < datetime(2026, 8, 25, tzinfo=UTC)
        or proof.get("account_status") != "ACTIVE"
        or any(
            proof.get(key) is not True
            for key in ("positions_empty", "orders_empty", "open_orders_empty")
        )
        or proof.get("order_history_disposition") != "empty-first-page"
        or proof.get("activity_history_disposition") != "empty-first-page"
        or proof.get("order_page_count") != 1
        or proof.get("activity_page_count") != 1
        or proof.get("raw_responses_persisted") is not False
        or proof.get("market_data_requested") is not False
        or proof.get("broker_write_requested") is not False
        or not _is_sha256(proof.get("account_identity_hash"))
        or not _is_sha256(proof.get("account_number_hash"))
        or not _is_sha256(proof.get("credential_key_id_hash"))
    ):
        raise ValueError("Program 002 account-isolation proof differs")
    expected_funding = (
        "paper-credential-has-no-live-host-authority"
        if proof["environment"] == "paper"
        else "live-account-balance-and-market-value-fields-are-zero"
    )
    if proof.get("funding_isolation_assertion") != expected_funding:
        raise ValueError("Program 002 account funding-isolation proof differs")


def _verify_account_isolation_proof_review(review: Mapping[str, Any]) -> None:
    unsigned = dict(review)
    review_fingerprint = unsigned.pop("review_fingerprint", None)
    if (
        review.get("schema_version") != "program-002-account-isolation-proof-independent-review-v1"
        or review.get("program_id") != PROGRAM_ID
        or review.get("status") != "passed-before-proof-bound-acquisition-authority"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review_fingerprint != REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_FINGERPRINT
        or fingerprint(unsigned) != REVIEWED_ACCOUNT_ISOLATION_PROOF_REVIEW_FINGERPRINT
        or review.get("reviewed_proof")
        != {
            "path": ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACCOUNT_ISOLATION_PROOF_SHA256,
            "fingerprint": REVIEWED_ACCOUNT_ISOLATION_PROOF_FINGERPRINT,
        }
        or any(_mapping(review.get("authority"), "proof review authority").values())
    ):
        raise ValueError("Program 002 account-isolation proof review differs")


def _verify_acquisition_pagination_amendment(repository: Path) -> None:
    failure_path = repository / ACQUISITION_PAGINATION_FAILURE_RELATIVE_PATH
    amendment_path = repository / ACQUISITION_PAGINATION_AMENDMENT_RELATIVE_PATH
    review_path = repository / ACQUISITION_PAGINATION_AMENDMENT_REVIEW_RELATIVE_PATH
    failure_raw = failure_path.read_bytes()
    amendment_raw = amendment_path.read_bytes()
    review_raw = review_path.read_bytes()
    _require_sha256(
        failure_raw,
        REVIEWED_ACQUISITION_PAGINATION_FAILURE_SHA256,
        "Program 002 pagination failure",
    )
    _require_sha256(
        amendment_raw,
        REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_SHA256,
        "Program 002 pagination amendment",
    )
    _require_sha256(
        review_raw,
        REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_REVIEW_SHA256,
        "Program 002 pagination amendment review",
    )
    failure = _load_unique_json(failure_raw, "Program 002 pagination failure")
    amendment = _load_unique_json(amendment_raw, "Program 002 pagination amendment")
    review = _load_unique_json(review_raw, "Program 002 pagination amendment review")

    unsigned_failure = dict(failure)
    if (
        failure.get("schema_version") != "program-002-exposed-acquisition-pagination-failure-v1"
        or unsigned_failure.pop("incident_fingerprint", None)
        != REVIEWED_ACQUISITION_PAGINATION_FAILURE_FINGERPRINT
        or fingerprint(unsigned_failure) != REVIEWED_ACQUISITION_PAGINATION_FAILURE_FINGERPRINT
        or failure.get("acquisition_attempt_id") != "program-002-exposed-acquisition-20260826-v2"
        or _mapping(failure.get("result"), "pagination failure result").get(
            "final_dataset_published"
        )
        is not False
        or any(_mapping(failure.get("protected_access"), "pagination protected access").values())
    ):
        raise ValueError("Program 002 pagination failure differs")
    _require_false_authority(failure.get("authority"), "pagination failure")

    unsigned_amendment = dict(amendment)
    if (
        amendment.get("schema_version") != "program-002-acquisition-pagination-amendment-v1"
        or amendment.get("status") != "PROSPECTIVE-PAGINATION-REPAIR-NOT-AUTHORIZED-FOR-ACQUISITION"
        or unsigned_amendment.pop("amendment_fingerprint", None)
        != REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_FINGERPRINT
        or fingerprint(unsigned_amendment) != REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_FINGERPRINT
        or amendment.get("base_acquisition_plan")
        != {
            "path": ACQUISITION_PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PLAN_SHA256,
            "disposition": "immutable-base-plan-amended-only-for-bar-page-resource-ceiling",
        }
        or amendment.get("prior_acquisition_authority")
        != {
            "path": ACQUISITION_AUTHORITY_V4_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_V4_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_V4_FINGERPRINT,
            "disposition": "immutable-runtime-failed-on-pagination-resource-ceiling",
        }
        or amendment.get("prior_acquisition_authority_review")
        != {
            "path": ACQUISITION_AUTHORITY_REVIEW_V2_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V2_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V2_FINGERPRINT,
        }
        or amendment.get("runtime_failure")
        != {
            "path": ACQUISITION_PAGINATION_FAILURE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PAGINATION_FAILURE_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_PAGINATION_FAILURE_FINGERPRINT,
        }
        or amendment.get("pagination_change")
        != {
            "bar_segment_project_page_ceiling_before": 10,
            "bar_segment_project_page_ceiling_after": 100,
            "quote_segment_project_page_ceiling": 100,
            "provider_limit_parameter": 10000,
            "page_ceiling_semantics": (
                "The project ceiling bounds resource use; it is not a provider page limit. "
                "Drain unique next_page_token values through null. If token pagination remains "
                "nonterminal after page 100, fail without segment or dataset publication and "
                "require another reviewed proposal."
            ),
            "reason": (
                "Use the existing reviewed quote-page ceiling for monthly bars because the "
                "provider may underfill pages and the observed valid context chain remained "
                "nonterminal after page ten."
            ),
        }
        or any(
            value is not True
            for value in _mapping(amendment.get("unchanged"), "pagination unchanged scope").values()
        )
        or any(
            value is not False
            for value in _mapping(
                amendment.get("launch_control"), "pagination launch control"
            ).values()
        )
    ):
        raise ValueError("Program 002 pagination amendment differs")
    _require_false_authority(amendment.get("authority"), "pagination amendment")

    unsigned_review = dict(review)
    if (
        review.get("schema_version")
        != "program-002-acquisition-pagination-amendment-independent-review-v1"
        or review.get("status") != "passed-before-pagination-implementation"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("reviewed_commit") != REVIEWED_ACQUISITION_PAGINATION_PROPOSAL_COMMIT
        or unsigned_review.pop("review_fingerprint", None)
        != REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_REVIEW_FINGERPRINT
        or fingerprint(unsigned_review)
        != REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_REVIEW_FINGERPRINT
        or review.get("reviewed_failure")
        != {
            "path": ACQUISITION_PAGINATION_FAILURE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PAGINATION_FAILURE_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_PAGINATION_FAILURE_FINGERPRINT,
        }
        or review.get("reviewed_amendment")
        != {
            "path": ACQUISITION_PAGINATION_AMENDMENT_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_FINGERPRINT,
        }
        or any(
            value is not True
            for value in _mapping(review.get("checks"), "pagination review checks").values()
        )
    ):
        raise ValueError("Program 002 pagination amendment review differs")
    _require_false_authority(review.get("authority"), "pagination amendment review")


def _verify_acquisition_authority_v5(
    repository: Path, payload: Mapping[str, Any], proof: Mapping[str, Any]
) -> None:
    unsigned = dict(payload)
    authority_fingerprint = unsigned.pop("authority_fingerprint", None)
    source = _mapping(payload.get("source_binding"), "acquisition authority source binding")
    files = source.get("files")
    if (
        payload.get("schema_version") != "program-002-exposed-acquisition-authority-v5"
        or payload.get("authority_id") != "program-002-exposed-acquisition-2026-08-26-v5"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "active-until-complete-or-terminal-blocker"
        or payload.get("source_authorization")
        != {
            "kind": "user-supplied-authorization-packet",
            "sha256": "fd1a468fb152c6c18c0babda29c8393507a68558161b325d7f17348422093480",
        }
        or authority_fingerprint != fingerprint(unsigned)
        or not _is_commit(source.get("source_commit"))
        or source.get("proof_evidence_commit") != REVIEWED_ACCOUNT_ISOLATION_PROOF_COMMIT
        or source.get("relationship")
        != "ancestor-of-clean-synchronized-main-with-identical-bound-files"
        or not isinstance(files, list)
        or [item.get("path") if isinstance(item, Mapping) else None for item in files]
        != list(ACQUISITION_SOURCE_PATHS)
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"path", "sha256"}
            or not _is_sha256(item.get("sha256"))
            or hashlib.sha256((repository / str(item.get("path"))).read_bytes()).hexdigest()
            != item.get("sha256")
            for item in files
        )
    ):
        raise ValueError("Program 002 acquisition authority identity or source differs")
    if payload.get("supersedes") != {
        "path": ACQUISITION_AUTHORITY_V4_RELATIVE_PATH.as_posix(),
        "sha256": REVIEWED_ACQUISITION_AUTHORITY_V4_SHA256,
        "disposition": "immutable-runtime-failed-on-pagination-resource-ceiling",
    }:
        raise ValueError("Program 002 acquisition authority supersession differs")
    expected_bindings = _expected_acquisition_authority_bindings()
    if payload.get("bindings") != expected_bindings:
        raise ValueError("Program 002 acquisition authority bindings differ")
    for binding in expected_bindings.values():
        _require_sha256(
            (repository / str(binding["path"])).read_bytes(),
            str(binding["sha256"]),
            str(binding["path"]),
        )
    plan_payload = _load_unique_json(
        (repository / ACQUISITION_PLAN_RELATIVE_PATH).read_bytes(),
        "Program 002 acquisition plan",
    )
    if payload.get("authorized_scope") != _expected_acquisition_scope(plan_payload):
        raise ValueError("Program 002 acquisition authority scope differs")
    account = _mapping(payload.get("account_isolation"), "acquisition account isolation")
    if account != {
        "proof_accepted": True,
        "environment": proof.get("environment"),
        "account_identity_hash": proof.get("account_identity_hash"),
        "credential_key_id_hash": proof.get("credential_key_id_hash"),
    }:
        raise ValueError("Program 002 acquisition authority account binding differs")
    expected_authority = {key: False for key in _AUTHORITY_KEYS}
    expected_authority.update({"market_data_acquisition": True, "strategy_implementation": True})
    if payload.get("authority") != expected_authority:
        raise ValueError("Program 002 acquisition authority flags differ")
    prohibited = _mapping(payload.get("prohibited"), "Program 002 prohibited acquisition scope")
    if set(prohibited) != {
        "strategy_execution_on_acquired_data",
        "strategy_result_generation_or_read",
        "discovery",
        "walk_forward",
        "robustness",
        "controlled_dataset_acquisition_or_access",
        "qualification",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
        "strategic_allocation_21_access",
    } or any(value is not True for value in prohibited.values()):
        raise ValueError("Program 002 prohibited acquisition scope differs")


def _expected_acquisition_authority_bindings() -> Mapping[str, Any]:
    return {
        "program_plan": {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLAN_SHA256,
            "fingerprint": REVIEWED_PLAN_FINGERPRINT,
        },
        "acquisition_plan": {
            "path": ACQUISITION_PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PLAN_SHA256,
        },
        "universe": {
            "path": UNIVERSE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_UNIVERSE_SHA256,
            "fingerprint": REVIEWED_UNIVERSE_FINGERPRINT,
        },
        "implementation_plan": {
            "path": IMPLEMENTATION_PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_IMPLEMENTATION_PLAN_SHA256,
        },
        "planning_review": {
            "path": PLANNING_REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLANNING_REVIEW_SHA256,
            "fingerprint": REVIEWED_PLANNING_REVIEW_FINGERPRINT,
        },
        "acquisition_control_amendment": {
            "path": ACQUISITION_CONTROL_AMENDMENT_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_CONTROL_AMENDMENT_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_CONTROL_AMENDMENT_FINGERPRINT,
        },
        "provider_contract_evidence": {
            "path": PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
            "fingerprint": REVIEWED_PROVIDER_CONTRACT_EVIDENCE_FINGERPRINT,
        },
        "acquisition_control_repair_review": {
            "path": ACQUISITION_CONTROL_REPAIR_REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_CONTROL_REPAIR_REVIEW_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_CONTROL_REPAIR_REVIEW_FINGERPRINT,
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
        "prior_acquisition_authority": {
            "path": ACQUISITION_AUTHORITY_V2_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_V2_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_V2_FINGERPRINT,
        },
        "prior_acquisition_authority_review": {
            "path": ACQUISITION_AUTHORITY_REVIEW_V1_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V1_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V1_FINGERPRINT,
        },
        "acquisition_runtime_failure": {
            "path": ACQUISITION_RUNTIME_FAILURE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_RUNTIME_FAILURE_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_RUNTIME_FAILURE_FINGERPRINT,
        },
        "rejected_acquisition_authority": {
            "path": ACQUISITION_AUTHORITY_V3_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_V3_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_V3_FINGERPRINT,
        },
        "rejected_acquisition_authority_review_failure": {
            "path": ACQUISITION_AUTHORITY_V3_REVIEW_FAILURE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_V3_REVIEW_FAILURE_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_V3_REVIEW_FAILURE_FINGERPRINT,
        },
        "runtime_failed_acquisition_authority": {
            "path": ACQUISITION_AUTHORITY_V4_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_V4_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_V4_FINGERPRINT,
        },
        "runtime_failed_acquisition_authority_review": {
            "path": ACQUISITION_AUTHORITY_REVIEW_V2_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V2_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_AUTHORITY_REVIEW_V2_FINGERPRINT,
        },
        "acquisition_pagination_failure": {
            "path": ACQUISITION_PAGINATION_FAILURE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PAGINATION_FAILURE_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_PAGINATION_FAILURE_FINGERPRINT,
        },
        "acquisition_pagination_amendment": {
            "path": ACQUISITION_PAGINATION_AMENDMENT_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_FINGERPRINT,
        },
        "acquisition_pagination_amendment_review": {
            "path": ACQUISITION_PAGINATION_AMENDMENT_REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_REVIEW_SHA256,
            "fingerprint": REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_REVIEW_FINGERPRINT,
        },
        "regulatory_fee_source": {
            "path": COST_MODEL_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_COST_MODEL_SHA256,
            "fingerprint": REVIEWED_COST_MODEL_FINGERPRINT,
        },
    }


def _expected_acquisition_scope(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    data = _mapping(plan.get("data_classes"), "acquisition data classes")
    exposed = _mapping(data.get("A_exposed_research_and_development"), "exposed acquisition data")
    context = _mapping(data.get("B_context_only"), "context acquisition data")
    quotes = _mapping(plan.get("quote_cost_calibration"), "quote calibration")
    bars = _mapping(plan.get("historical_bars"), "historical bars")
    datasets = [context.get("exposed_dataset"), *list(exposed.get("datasets", []))]
    return {
        "symbols": quotes.get("symbols"),
        "bars": {
            "endpoint": bars.get("endpoint"),
            "http_method": "GET",
            "feed": "sip",
            "timeframe": "5Min",
            "adjustment": "all",
            "adjustment_policy": "provider-adjusted-all-v1",
            "calendar_policy": "XNYS-regular-session-bars-v1",
            "timestamp_policy": "bar-open-utc-v1",
            "start_semantics": "inclusive",
            "end_semantics": "inclusive",
            "datasets": datasets,
        },
        "quotes": {
            "endpoint": quotes.get("endpoint"),
            "http_method": "GET",
            "feed": "sip",
            "sessions": quotes.get("sessions"),
            "fill_clocks_new_york": quotes.get("fill_clocks_new_york"),
        },
        "controlled_block_a": False,
        "controlled_block_b": False,
        "protected_data": False,
    }


def _verify_authority(repository: Path, payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_version") != "program-002-implementation-acquisition-authority-v1"
        or payload.get("authority_id") != "program-002-implementation-acquisition-2026-08-25-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "active-until-complete-or-terminal-blocker"
        or payload.get("issued_date") != "2026-08-25"
        or payload.get("source")
        != {
            "kind": "user-supplied-authorization-packet",
            "sha256": REVIEWED_AUTHORIZATION_PACKET_SHA256,
        }
    ):
        raise ValueError("Program 002 authority identity differs")
    expected_bindings = {
        "program_plan": {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLAN_SHA256,
            "fingerprint": REVIEWED_PLAN_FINGERPRINT,
        },
        "acquisition_plan": {
            "path": ACQUISITION_PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PLAN_SHA256,
        },
        "universe": {
            "path": UNIVERSE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_UNIVERSE_SHA256,
            "fingerprint": REVIEWED_UNIVERSE_FINGERPRINT,
        },
        "implementation_plan": {
            "path": IMPLEMENTATION_PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_IMPLEMENTATION_PLAN_SHA256,
        },
        "planning_review": {
            "path": PLANNING_REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLANNING_REVIEW_SHA256,
            "fingerprint": REVIEWED_PLANNING_REVIEW_FINGERPRINT,
        },
    }
    if payload.get("bindings") != expected_bindings:
        raise ValueError("Program 002 authority bindings differ")
    for binding in expected_bindings.values():
        artifact = repository / str(binding["path"])
        _require_sha256(artifact.read_bytes(), str(binding["sha256"]), artifact.as_posix())
    authority_symbols = (*_RANKING_SYMBOLS[:2], _SPY, *_RANKING_SYMBOLS[2:])
    expected_symbols = [symbol.value for symbol in authority_symbols]
    if payload.get("authorized") != {
        "strategy_implementation": True,
        "synthetic_and_mock_validation": True,
        "exposed_market_data_acquisition": True,
        "exposed_quote_calibration_acquisition": True,
        "prospective_cost_model_derivation": True,
        "authorized_dataset_roles": [
            "exposed-context-only",
            "exposed-block-1",
            "exposed-block-2",
            "exposed-block-3",
        ],
        "quote_sessions": 73,
        "quote_fill_clocks": 9,
        "symbols": expected_symbols,
    }:
        raise ValueError("Program 002 authorized scope differs")
    prohibited = _mapping(payload.get("prohibited"), "Program 002 prohibited scope")
    if set(prohibited) != {
        "strategy_execution_on_acquired_data",
        "strategy_result_generation_or_read",
        "discovery",
        "walk_forward",
        "robustness",
        "controlled_dataset_acquisition_or_access",
        "qualification",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
        "strategic_allocation_21_access",
    } or any(value is not True for value in prohibited.values()):
        raise ValueError("Program 002 prohibited scope differs")
    expected_authority = {key: False for key in _AUTHORITY_KEYS}
    expected_authority.update({"market_data_acquisition": True, "strategy_implementation": True})
    if payload.get("authority") != expected_authority:
        raise ValueError("Program 002 authority flags differ")


def _verify_plan_identity(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_version") != "cross-sectional-sector-etf-program-002-plan-proposal-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "PROPOSED-NOT-AUTHORIZED"
    ):
        raise ValueError("Program 002 plan identity differs")
    unsigned = dict(payload)
    if unsigned.pop("plan_fingerprint", None) != REVIEWED_PLAN_FINGERPRINT:
        raise ValueError("Program 002 plan fingerprint binding differs")
    if fingerprint(unsigned) != REVIEWED_PLAN_FINGERPRINT:
        raise ValueError("Program 002 plan fingerprint differs")
    _require_false_authority(payload.get("authority"), "plan")
    launch = _mapping(payload.get("launch_control"), "plan launch control")
    if set(launch.values()) != {False}:
        raise ValueError("Program 002 plan unexpectedly grants launch authority")


def _verify_universe(payload: Mapping[str, Any], universe: Mapping[str, Any]) -> None:
    binding = _mapping(payload.get("universe"), "plan universe binding")
    if (
        binding.get("path") != UNIVERSE_RELATIVE_PATH.as_posix()
        or binding.get("sha256") != REVIEWED_UNIVERSE_SHA256
        or binding.get("universe_fingerprint") != REVIEWED_UNIVERSE_FINGERPRINT
        or binding.get("ranking_symbols") != [symbol.value for symbol in _RANKING_SYMBOLS]
        or binding.get("context_and_benchmark_symbol") != _SPY.value
        or binding.get("membership_change_allowed") is not False
    ):
        raise ValueError("Program 002 universe binding differs")
    if (
        universe.get("id") != "multi-hour-sector-etfs-v1"
        or universe.get("timeframe") != "5m"
        or universe.get("traded_symbols") != [symbol.value for symbol in _RANKING_SYMBOLS]
        or universe.get("ranking_symbols") != [symbol.value for symbol in _RANKING_SYMBOLS]
        or universe.get("context_and_benchmark_symbols") != [_SPY.value]
        or fingerprint(universe) != REVIEWED_UNIVERSE_FINGERPRINT
    ):
        raise ValueError("Program 002 universe contract differs")
    _require_false_authority(universe.get("authority"), "universe")


def _configurations(payload: Mapping[str, Any]) -> dict[str, Program002Configuration]:
    grid = _mapping(payload.get("configuration_grid"), "configuration grid")
    strategy_by_family = {
        _text(item, "family_id"): _text(item, "strategy_id")
        for item in _list_of_mappings(payload.get("economic_contracts"), "economic contracts")
    }
    result: dict[str, Program002Configuration] = {}
    for item in _list_of_mappings(grid.get("configurations"), "configurations"):
        configuration_id = _text(item, "configuration_id")
        family_id = _text(item, "family_id")
        neighbors = item.get("immediate_neighbors")
        if (
            configuration_id in result
            or family_id not in strategy_by_family
            or not isinstance(neighbors, list)
            or len(neighbors) != 2
            or not all(isinstance(value, str) and value for value in neighbors)
        ):
            raise ValueError("Program 002 configuration identity differs")
        lookback = item.get("lookback_30m_bars")
        hold = item.get("hold_30m_bars")
        if (
            type(lookback) is not int
            or lookback not in {1, 2}
            or type(hold) is not int
            or hold not in {4, 8}
        ):
            raise ValueError("Program 002 configuration axes differ")
        result[configuration_id] = Program002Configuration(
            configuration_id,
            family_id,
            strategy_by_family[family_id],
            lookback,
            hold,
            (neighbors[0], neighbors[1]),
        )
    if grid.get("configuration_count") != 8 or len(result) != 8:
        raise ValueError("Program 002 configuration count differs")
    return result


def _verify_contracts(
    payload: Mapping[str, Any], configurations: Mapping[str, Program002Configuration]
) -> None:
    expected_families = {
        "sector-relative-continuation-v1": (
            "multi-hour-sector-relative-continuation-v1",
            "residual_return > 0 and same_clock_relative_volume >= 1.2",
            "residual_return descending, then symbol ascending",
        ),
        "sector-relative-reversal-v1": (
            "multi-hour-sector-relative-reversal-v1",
            "residual_return <= -0.001 and same_clock_relative_volume >= 1.5",
            "residual_return ascending, then symbol ascending",
        ),
    }
    families = {
        _text(item, "family_id"): (
            _text(item, "strategy_id"),
            _text(item, "activation"),
            _text(item, "ranking"),
        )
        for item in _list_of_mappings(payload.get("economic_contracts"), "economic contracts")
    }
    if families != expected_families:
        raise ValueError("Program 002 economic contracts differ")
    for configuration in configurations.values():
        for neighbor_id in configuration.immediate_neighbors:
            neighbor = configurations.get(neighbor_id)
            if neighbor is None or neighbor.family_id != configuration.family_id:
                raise ValueError("Program 002 neighbor graph differs")
            changed = sum(
                left != right
                for left, right in (
                    (configuration.lookback_30m_bars, neighbor.lookback_30m_bars),
                    (configuration.hold_30m_bars, neighbor.hold_30m_bars),
                )
            )
            if changed != 1 or configuration.configuration_id not in neighbor.immediate_neighbors:
                raise ValueError("Program 002 neighbor graph differs")
    budget = _mapping(payload.get("campaigns_and_budget"), "campaign budget")
    if (
        _mapping(budget.get("campaign_1"), "campaign 1").get("maximum_specs") != 114
        or _mapping(budget.get("campaign_2"), "campaign 2").get("maximum_specs") != 114
        or budget.get("controlled_specs") != 4
        or budget.get("maximum_run_specifications") != 232
        or budget.get("maximum_attempts_per_specification") != 3
        or budget.get("maximum_infrastructure_attempts") != 696
    ):
        raise ValueError("Program 002 budget differs")
    feature = _mapping(payload.get("feature_contract"), "feature contract")
    decision = _mapping(feature.get("decision"), "decision contract")
    execution = _mapping(payload.get("execution_contract"), "execution contract")
    portfolio = _mapping(payload.get("portfolio_contract"), "portfolio contract")
    if (
        decision.get("clock") != "11:30:00 America/New_York"
        or decision.get("latest_source_bar_open") != "11:25:00 America/New_York"
        or feature.get("numeric_policy") != _NUMERIC_POLICY
        or portfolio.get("construction") != "long-flat"
        or portfolio.get("maximum_positions") != 3
        or portfolio.get("shorting") is not False
        or portfolio.get("leverage") is not False
        or portfolio.get("reentry") is not False
        or portfolio.get("resize") is not False
        or execution.get("entry_fill_clocks")
        != {"delay_1": "11:35", "delay_2": "11:40", "delay_3": "11:45"}
    ):
        raise ValueError("Program 002 causal portfolio contract differs")


def _require_false_authority(value: object, label: str) -> None:
    authority = _mapping(value, f"{label} authority")
    if set(authority) != _AUTHORITY_KEYS or any(item is not False for item in authority.values()):
        raise ValueError(f"Program 002 {label} authority differs")


def _load_unique_json(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    return _mapping(value, label)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_sha256(raw: bytes, expected: str, label: str) -> None:
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"{label} SHA-256 differs")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be text")
    return item


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
