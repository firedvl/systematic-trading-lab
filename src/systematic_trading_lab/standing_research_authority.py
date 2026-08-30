"""Standing authorization checks for prospective exposed-research children."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .fingerprints import fingerprint

MANDATE_PATH = Path("config/research/standing-autonomous-research-mandate-v1.json")
MANDATE_REVIEW_PATH = Path(
    "config/research/standing-autonomous-research-mandate-independent-review-v1.json"
)
MANDATE_ID = "standing-autonomous-research-mandate-2026-08-30-v1"
MANDATE_FINGERPRINT = "3465648952ccc094697c8edc24860658c6098235989a868610c1e1b12746d502"
MANDATE_REVIEWED_SOURCE_PATHS = (
    MANDATE_PATH,
    Path("docs/README.md"),
    Path("docs/research-campaigns/standing-autonomous-research-mandate-v1.txt"),
    Path("docs/research-policy.md"),
    Path("docs/standing-autonomous-research-mandate.md"),
    Path("docs/threat-model.md"),
    Path("src/systematic_trading_lab/standing_research_authority.py"),
    Path("tests/unit/test_standing_research_authority.py"),
)

AUTHORITY_FIELDS = frozenset(
    {
        "provider_contact",
        "subscription_purchase",
        "credential_access",
        "source_requests",
        "source_qualification",
        "market_data_acquisition",
        "real_dataset_admission",
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
FORBIDDEN_CHILD_AUTHORITY = frozenset(
    {
        "subscription_purchase",
        "controlled_evaluation",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
    }
)
MANDATE_REVIEW_CHALLENGES = frozenset(
    {
        "authority-origin",
        "scope-containment",
        "controlled-and-protected-firewall",
        "credential-confinement",
        "purchase-firewall",
        "prospective-scientific-integrity",
        "historical-authority-immutability",
        "runtime-revalidation",
        "one-use-replay-safety",
        "private-evidence-boundary",
    }
)
PROGRAM_010_CHILD_AUTHORITY_ID = (
    "program-010-raw-alpaca-sip-ohlcv-structural-qualification-authority-2026-08-30-v1"
)
PROGRAM_010_CHILD_OPERATION_KIND = "PROGRAM-010-RAW-SIP-OHLCV-STRUCTURAL-QUALIFICATION"
PROGRAM_010_CHILD_ENABLED_AUTHORITY = frozenset(
    {"provider_contact", "credential_access", "source_requests", "source_qualification"}
)
PROGRAM_010_CHILD_REVIEW_CHALLENGES = (
    "standing-mandate-and-review-binding",
    "program-005-through-009-history-preservation",
    "fresh-exposed-chronology-and-protected-firewall",
    "fixed-get-endpoint-query-and-redirect-rejection",
    "credential-confinement-and-no-value-disclosure",
    "pagination-resource-and-zero-retry-budgets",
    "raw-first-private-create-only-evidence",
    "one-use-claim-replay-and-terminal-failure",
    "source-coverage-missingness-and-no-imputation",
    "git-lineage-and-runtime-revalidation",
    "no-dataset-strategy-controlled-paper-broker-or-live-authority",
)
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")


class StandingAuthorityError(ValueError):
    """The standing mandate or a prospective child failed closed."""


def load_standing_mandate(repository: Path) -> Mapping[str, Any]:
    """Load the exact user grant and its finding-free control review."""
    repository = _repository(repository)
    mandate, _, _ = _load_standing_controls(repository)
    return mandate


def _load_standing_controls(
    repository: Path,
) -> tuple[Mapping[str, Any], Mapping[str, str], Mapping[str, str]]:
    mandate, mandate_binding = _load_fingerprinted_artifact(
        repository, MANDATE_PATH, "mandate_fingerprint", "standing mandate"
    )
    _validate_mandate(repository, mandate)
    review, review_binding = _load_fingerprinted_artifact(
        repository, MANDATE_REVIEW_PATH, "review_fingerprint", "standing mandate review"
    )
    _validate_mandate_review(repository, review, mandate_binding)
    return mandate, mandate_binding, review_binding


def derive_child_identity(
    repository: Path,
    child_path: Path,
    review_path: Path,
) -> Mapping[str, Any]:
    """Derive a reviewed child identity without activating its concrete runtime."""
    repository = _repository(repository)
    child_path = _program_010_control_path(child_path, "child authority path")
    review_path = _program_010_control_path(review_path, "child review path")
    if child_path == review_path:
        raise StandingAuthorityError("child authority and review paths must differ")
    mandate, mandate_binding, mandate_review_binding = _load_standing_controls(repository)
    child, child_binding = _load_fingerprinted_artifact(
        repository, child_path, "child_authority_fingerprint", "child authority"
    )
    review, review_binding = _load_fingerprinted_artifact(
        repository, review_path, "review_fingerprint", "child authority review"
    )
    _validate_child(repository, child, mandate, mandate_binding)
    _validate_child_review(review, child_binding)

    unsigned: dict[str, Any] = {
        "schema_version": "standing-autonomous-research-child-identity-v1",
        "status": "REVIEWED-READY-FOR-RUNTIME-ACTIVATION",
        "activation_mode": "INTERNAL-DERIVATION-FROM-EXACT-STANDING-USER-MANDATE",
        "external_authorization_root_required": False,
        "runtime_revalidation_required_before_active_state": True,
        "child_authority_id": child["child_authority_id"],
        "program_ordinal": child["program_ordinal"],
        "program_id": child["program_id"],
        "operation_kind": child["operation_kind"],
        "consumption_boundary": child["consumption_boundary"],
        "standing_mandate": mandate_binding,
        "standing_mandate_review": mandate_review_binding,
        "child_authority": child_binding,
        "child_review": review_binding,
        "data_classes": child["data_classes"],
        "authority": child["authority"],
    }
    return {**unsigned, "child_identity_fingerprint": fingerprint(unsigned)}


def _validate_mandate(repository: Path, mandate: Mapping[str, Any]) -> None:
    source = _mapping(mandate.get("source_grant"), "source grant")
    activation = _mapping(mandate.get("activation_contract"), "activation contract")
    data_scope = _mapping(mandate.get("data_scope"), "data scope")
    authority = _authority(mandate.get("authority"), "standing authority")
    source_path = _relative_path(source.get("path"), "source grant path")
    source_bytes = _read_regular_file(repository, source_path, "source grant")
    if (
        mandate.get("schema_version") != "standing-autonomous-research-mandate-v1"
        or mandate.get("mandate_id") != MANDATE_ID
        or mandate.get("project") != "firedvl/systematic-trading-lab"
        or mandate.get("status") != "ACTIVE-STANDING-AUTONOMOUS-EXPOSED-RESEARCH-MANDATE"
        or mandate.get("mandate_fingerprint") != MANDATE_FINGERPRINT
        or hashlib.sha256(source_bytes).hexdigest() != source.get("sha256")
        or len(source_bytes) != source.get("byte_count")
        or len(source_bytes.splitlines()) != source.get("line_count")
        or source.get("exact_user_bytes_committed") is not True
        or source.get("contains_secrets") is not False
        or activation.get("minimum_program_ordinal") != 10
        or activation.get("scoped_child_authority_required") is not True
        or activation.get("finding_free_independent_review_required") is not True
        or activation.get("runtime_revalidation_required") is not True
        or activation.get("internal_child_identity_derivation") is not True
        or activation.get("later_external_user_root_required") is not False
        or activation.get("programs_005_through_009_external_root_semantics_unchanged") is not True
        or activation.get("child_scope_must_be_subset_of_mandate") is not True
        or activation.get("review_is_error_detection_not_authorization") is not True
        or set(_strings(data_scope.get("permitted_classes"), "permitted data classes"))
        != {"PUBLIC", "EXPOSED", "FRESH-PROSPECTIVE-EXPOSED"}
        or data_scope.get("controlled_allowed") is not False
        or data_scope.get("protected_allowed") is not False
        or any(authority[field] for field in FORBIDDEN_CHILD_AUTHORITY)
    ):
        raise StandingAuthorityError("standing mandate semantics differ")


def _validate_mandate_review(
    repository: Path,
    review: Mapping[str, Any],
    mandate_binding: Mapping[str, str],
) -> None:
    implementation = _mapping(review.get("reviewed_implementation"), "reviewed implementation")
    source_files = _sequence(implementation.get("source_files"), "reviewed source files")
    challenges = _sequence(review.get("challenge_results"), "mandate review challenges")
    authority = _authority(review.get("authority"), "mandate review authority")
    if (
        review.get("schema_version") != "standing-autonomous-research-mandate-independent-review-v1"
        or review.get("review_id")
        != "standing-autonomous-research-mandate-independent-review-2026-08-30-v1"
        or review.get("status") != "PASS-FINDING-FREE"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or review.get("reviewed_mandate") != mandate_binding
        or _HEX_40.fullmatch(str(implementation.get("source_commit"))) is None
        or _HEX_40.fullmatch(str(implementation.get("source_tree"))) is None
        or implementation.get("implementation_root") != fingerprint(source_files)
        or [item.get("path") for item in source_files if isinstance(item, Mapping)]
        != [path.as_posix() for path in MANDATE_REVIEWED_SOURCE_PATHS]
        or {item.get("challenge") for item in challenges if isinstance(item, Mapping)}
        != MANDATE_REVIEW_CHALLENGES
        or any(
            not isinstance(item, Mapping) or item.get("verdict") != "PASS" for item in challenges
        )
        or any(authority.values())
    ):
        raise StandingAuthorityError("standing mandate review semantics differ")
    for item in source_files:
        binding = _mapping(item, "reviewed source file")
        path = _relative_path(binding.get("path"), "reviewed source path")
        raw = _read_regular_file(repository, path, "reviewed source file")
        if hashlib.sha256(raw).hexdigest() != binding.get("sha256"):
            raise StandingAuthorityError("reviewed standing-authority source differs")


def _validate_child(
    repository: Path,
    child: Mapping[str, Any],
    mandate: Mapping[str, Any],
    mandate_binding: Mapping[str, str],
) -> None:
    authority = _authority(child.get("authority"), "child authority")
    standing = _authority(mandate.get("authority"), "standing authority")
    data_scope = _mapping(mandate.get("data_scope"), "standing data scope")
    data_classes = set(_strings(child.get("data_classes"), "child data classes"))
    permitted_classes = set(_strings(data_scope.get("permitted_classes"), "permitted data classes"))
    bindings = _mapping(child.get("bindings"), "child bindings")
    runtime = _mapping(child.get("runtime_binding"), "child runtime binding")
    required_challenges = _strings(
        child.get("required_review_challenges"), "child required review challenges"
    )
    program_ordinal = child.get("program_ordinal")
    if (
        child.get("schema_version") != "standing-autonomous-research-child-authority-v1"
        or child.get("status") != "READY-FOR-STANDING-ACTIVATION"
        or program_ordinal != 10
        or child.get("child_authority_id") != PROGRAM_010_CHILD_AUTHORITY_ID
        or child.get("program_id") != "multi-hour-sector-etf-research-009"
        or child.get("operation_kind") != PROGRAM_010_CHILD_OPERATION_KIND
        or child.get("one_use") is not True
        or not isinstance(child.get("consumption_boundary"), str)
        or not child["consumption_boundary"]
        or child.get("standing_mandate") != mandate_binding
        or not bindings
        or not _valid_source_binding(runtime)
        or data_classes != {"FRESH-PROSPECTIVE-EXPOSED"}
        or not data_classes <= permitted_classes
        or authority
        != {field: field in PROGRAM_010_CHILD_ENABLED_AUTHORITY for field in AUTHORITY_FIELDS}
        or any(authority[field] and not standing[field] for field in AUTHORITY_FIELDS)
        or any(authority[field] for field in FORBIDDEN_CHILD_AUTHORITY)
        or required_challenges != PROGRAM_010_CHILD_REVIEW_CHALLENGES
    ):
        raise StandingAuthorityError("child authority exceeds the standing mandate")
    for value in bindings.values():
        _validate_artifact_binding(repository, _mapping(value, "child binding"))
    for value in _sequence(runtime["source_files"], "child runtime source files"):
        binding = _mapping(value, "child runtime source file")
        path = _relative_path(binding.get("path"), "child runtime source path")
        raw = _read_regular_file(repository, path, "child runtime source file")
        if hashlib.sha256(raw).hexdigest() != binding.get("sha256"):
            raise StandingAuthorityError("child runtime source differs")


def _validate_child_review(review: Mapping[str, Any], child_binding: Mapping[str, str]) -> None:
    authority = _authority(review.get("authority"), "child review authority")
    challenges = _sequence(review.get("challenge_results"), "child review challenges")
    challenge_names = [item.get("challenge") for item in challenges if isinstance(item, Mapping)]
    if (
        review.get("schema_version")
        != "standing-autonomous-research-child-authority-independent-review-v1"
        or review.get("status") != "PASS-FINDING-FREE"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or not isinstance(review.get("review_id"), str)
        or not review["review_id"]
        or review.get("reviewed_child_authority") != child_binding
        or challenge_names != list(PROGRAM_010_CHILD_REVIEW_CHALLENGES)
        or any(
            not isinstance(item, Mapping) or item.get("verdict") != "PASS" for item in challenges
        )
        or any(authority.values())
    ):
        raise StandingAuthorityError("child authority review semantics differ")


def _valid_source_binding(value: Mapping[str, Any]) -> bool:
    source_files = value.get("source_files")
    if not isinstance(source_files, Sequence) or isinstance(source_files, str | bytes | bytearray):
        return False
    paths = [item.get("path") for item in source_files if isinstance(item, Mapping)]
    return (
        _HEX_40.fullmatch(str(value.get("source_commit"))) is not None
        and _HEX_40.fullmatch(str(value.get("source_tree"))) is not None
        and bool(source_files)
        and len(paths) == len(source_files) == len(set(paths))
        and value.get("implementation_root") == fingerprint(source_files)
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("path"), str)
            and _HEX_64.fullmatch(str(item.get("sha256"))) is not None
            for item in source_files
        )
    )


def _validate_artifact_binding(repository: Path, binding: Mapping[str, Any]) -> None:
    path = _relative_path(binding.get("path"), "bound artifact path")
    raw = _read_regular_file(repository, path, "bound child artifact")
    if _HEX_64.fullmatch(str(binding.get("sha256"))) is None or hashlib.sha256(
        raw
    ).hexdigest() != binding.get("sha256"):
        raise StandingAuthorityError("bound child artifact differs")
    expected_fingerprint = binding.get("fingerprint")
    if expected_fingerprint is None:
        return
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StandingAuthorityError("bound child artifact is invalid JSON") from error
    if (
        _HEX_64.fullmatch(str(expected_fingerprint)) is None
        or not isinstance(payload, Mapping)
        or expected_fingerprint
        not in {value for key, value in payload.items() if key.endswith("_fingerprint")}
    ):
        raise StandingAuthorityError("bound child artifact fingerprint differs")


def _load_fingerprinted_artifact(
    repository: Path,
    relative: Path,
    fingerprint_field: str,
    label: str,
) -> tuple[Mapping[str, Any], Mapping[str, str]]:
    raw = _read_regular_file(repository, relative, label)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StandingAuthorityError(f"{label} is invalid JSON") from error
    if type(payload) is not dict:
        raise StandingAuthorityError(f"{label} is not an object")
    unsigned = dict(payload)
    stored = unsigned.pop(fingerprint_field, None)
    if _HEX_64.fullmatch(str(stored)) is None or stored != fingerprint(unsigned):
        raise StandingAuthorityError(f"{label} fingerprint differs")
    return payload, {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprint": str(stored),
    }


def _read_regular_file(repository: Path, relative: Path, label: str) -> bytes:
    path = repository / relative
    try:
        current = repository
        for part in relative.parts:
            current /= part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise StandingAuthorityError(f"{label} traverses a symbolic link")
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as error:
        raise StandingAuthorityError(f"{label} is absent") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise StandingAuthorityError(f"{label} is not a regular file")
    return raw


def _repository(repository: Path) -> Path:
    if not isinstance(repository, Path):
        raise StandingAuthorityError("repository root is invalid")
    resolved = repository.resolve()
    if not resolved.is_dir():
        raise StandingAuthorityError("repository root is absent")
    return resolved


def _relative_path(value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise StandingAuthorityError(f"{label} is invalid")
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise StandingAuthorityError(f"{label} is invalid")
    return path


def _program_010_control_path(value: Any, label: str) -> Path:
    if not isinstance(value, Path):
        raise StandingAuthorityError(f"{label} is invalid")
    path = _relative_path(value.as_posix(), label)
    if (
        path.parent != Path("config/research")
        or not path.name.startswith("program-010-")
        or path.suffix != ".json"
    ):
        raise StandingAuthorityError(f"{label} is outside the Program 010 control namespace")
    return path


def _authority(value: Any, label: str) -> Mapping[str, bool]:
    authority = _mapping(value, label)
    if set(authority) != AUTHORITY_FIELDS or any(
        type(item) is not bool for item in authority.values()
    ):
        raise StandingAuthorityError(f"{label} fields differ")
    return {str(key): value for key, value in authority.items()}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StandingAuthorityError(f"{label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise StandingAuthorityError(f"{label} is invalid")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    items = _sequence(value, label)
    if not items or any(not isinstance(item, str) or not item for item in items):
        raise StandingAuthorityError(f"{label} is invalid")
    return tuple(items)
