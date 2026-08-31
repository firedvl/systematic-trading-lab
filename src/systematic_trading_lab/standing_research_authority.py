"""Standing authorization checks for prospective exposed-research children."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
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
CHILD_REVIEW_REQUIRED_CHALLENGES = frozenset(
    {
        "data-leakage",
        "chronology",
        "freshness",
        "specification-changes",
        "request-budgets",
        "missingness-rules",
        "source-assumptions",
        "statistical-validity",
        "overfitting",
        "authority-boundaries",
        "private-data-leakage",
        "git-provenance-integrity",
    }
)
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_PROGRAM_CONTROL = re.compile(r"program-(?P<ordinal>[0-9]{3,})-.+\.json")


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
    child_path, child_ordinal = _child_control_path(child_path, "child authority path")
    review_path, review_ordinal = _child_control_path(review_path, "child review path")
    if child_path == review_path:
        raise StandingAuthorityError("child authority and review paths must differ")
    if child_ordinal != review_ordinal:
        raise StandingAuthorityError("child authority and review program ordinals differ")
    mandate, mandate_binding, mandate_review_binding = _load_standing_controls(repository)
    child, child_binding = _load_fingerprinted_artifact(
        repository, child_path, "child_authority_fingerprint", "child authority"
    )
    review, review_binding = _load_fingerprinted_artifact(
        repository, review_path, "review_fingerprint", "child authority review"
    )
    required_challenges = _validate_child(
        repository, child, mandate, mandate_binding, child_ordinal
    )
    _validate_child_review(review, child_binding, required_challenges)

    unsigned: dict[str, Any] = {
        "schema_version": "standing-autonomous-research-child-identity-v1",
        "status": "REVIEWED-CONTROL-IDENTITY",
        "activation_mode": "INTERNAL-DERIVATION-FROM-EXACT-STANDING-USER-MANDATE",
        "external_authorization_root_required": False,
        "runtime_activation_authorized": False,
        "concrete_runtime_validation_required": True,
        "runtime_revalidation_required_before_active_state": True,
        "atomic_one_use_claim_required": True,
        "terminal_evidence_required": True,
        "child_authority_id": child["child_authority_id"],
        "program_ordinal": child["program_ordinal"],
        "program_id": child["program_id"],
        "operation_kind": child["operation_kind"],
        "consumption_boundary": child["consumption_boundary"],
        "standing_mandate": mandate_binding,
        "standing_mandate_review": mandate_review_binding,
        "child_authority": child_binding,
        "child_review": review_binding,
        "operation_manifest": child["operation_manifest"],
        "runtime_binding": child["runtime_binding"],
        "runtime_entrypoint": child["runtime_entrypoint"],
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
    _validate_source_binding(repository, implementation, "reviewed standing-authority source")


def _validate_child(
    repository: Path,
    child: Mapping[str, Any],
    mandate: Mapping[str, Any],
    mandate_binding: Mapping[str, str],
    path_ordinal: int,
) -> tuple[str, ...]:
    authority = _authority(child.get("authority"), "child authority")
    standing = _authority(mandate.get("authority"), "standing authority")
    data_scope = _mapping(mandate.get("data_scope"), "standing data scope")
    data_classes = set(_strings(child.get("data_classes"), "child data classes"))
    permitted_classes = set(_strings(data_scope.get("permitted_classes"), "permitted data classes"))
    runtime = _mapping(child.get("runtime_binding"), "child runtime binding")
    runtime_entrypoint = _relative_path(child.get("runtime_entrypoint"), "runtime entrypoint")
    required_challenges = _strings(
        child.get("required_review_challenges"), "child required review challenges"
    )
    program_ordinal = child.get("program_ordinal")
    minimum_ordinal = _mapping(
        mandate.get("activation_contract"), "activation contract"
    ).get("minimum_program_ordinal")
    source_files = _sequence(runtime.get("source_files"), "child runtime source files")
    source_paths = {
        item.get("path") for item in source_files if isinstance(item, Mapping)
    }
    if (
        child.get("schema_version") != "standing-autonomous-research-child-authority-v1"
        or child.get("status") != "PROSPECTIVE-CHILD-CONTROL"
        or type(program_ordinal) is not int
        or type(minimum_ordinal) is not int
        or program_ordinal < minimum_ordinal
        or program_ordinal != path_ordinal
        or not _nonempty_string(child.get("child_authority_id"))
        or not _nonempty_string(child.get("program_id"))
        or not _nonempty_string(child.get("operation_kind"))
        or child.get("one_use") is not True
        or not _nonempty_string(child.get("consumption_boundary"))
        or child.get("concrete_runtime_validation_required") is not True
        or child.get("runtime_revalidation_required") is not True
        or child.get("atomic_one_use_claim_required") is not True
        or child.get("terminal_evidence_required") is not True
        or child.get("standing_mandate") != mandate_binding
        or not data_classes
        or not data_classes <= permitted_classes
        or any(authority[field] and not standing[field] for field in AUTHORITY_FIELDS)
        or any(authority[field] for field in FORBIDDEN_CHILD_AUTHORITY)
        or len(required_challenges) != len(set(required_challenges))
        or not set(required_challenges) >= CHILD_REVIEW_REQUIRED_CHALLENGES
        or runtime_entrypoint.as_posix() not in source_paths
        or runtime_entrypoint.parts[:2] != ("src", "systematic_trading_lab")
        or runtime_entrypoint.suffix != ".py"
    ):
        raise StandingAuthorityError("child authority exceeds the standing mandate")
    _validate_artifact_binding(
        repository, _mapping(child.get("operation_manifest"), "operation manifest")
    )
    _validate_source_binding(repository, runtime, "child runtime source")
    return required_challenges


def _validate_child_review(
    review: Mapping[str, Any],
    child_binding: Mapping[str, str],
    required_challenges: Sequence[str],
) -> None:
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
        or challenge_names != list(required_challenges)
        or any(
            not isinstance(item, Mapping) or item.get("verdict") != "PASS" for item in challenges
        )
        or any(authority.values())
    ):
        raise StandingAuthorityError("child authority review semantics differ")


def _validate_source_binding(
    repository: Path, value: Mapping[str, Any], label: str
) -> None:
    source_files = _sequence(value.get("source_files"), f"{label} files")
    commit = value.get("source_commit")
    tree = value.get("source_tree")
    paths = [item.get("path") for item in source_files if isinstance(item, Mapping)]
    if (
        _HEX_40.fullmatch(str(commit)) is None
        or _HEX_40.fullmatch(str(tree)) is None
        or not source_files
        or len(paths) != len(source_files)
        or len(set(paths)) != len(source_files)
        or value.get("implementation_root") != fingerprint(source_files)
    ):
        raise StandingAuthorityError(f"{label} provenance differs")
    resolved_commit = _git(repository, "rev-parse", "--verify", f"{commit}^{{commit}}")
    resolved_tree = _git(repository, "rev-parse", "--verify", f"{commit}^{{tree}}")
    if resolved_commit.decode().strip() != commit or resolved_tree.decode().strip() != tree:
        raise StandingAuthorityError(f"{label} Git provenance differs")
    for item in source_files:
        binding = _mapping(item, f"{label} file")
        path = _relative_path(binding.get("path"), f"{label} path")
        expected = binding.get("sha256")
        committed = _git(repository, "cat-file", "blob", f"{commit}:{path.as_posix()}")
        current = _read_regular_file(repository, path, f"{label} file")
        if (
            _HEX_64.fullmatch(str(expected)) is None
            or hashlib.sha256(committed).hexdigest() != expected
            or hashlib.sha256(current).hexdigest() != expected
        ):
            raise StandingAuthorityError(f"{label} differs from its Git tree")


def _git(repository: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise StandingAuthorityError("Git provenance cannot be verified") from error
    if result.returncode != 0:
        raise StandingAuthorityError("Git provenance cannot be verified")
    return result.stdout


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
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or path.parts[0] == ".git"
        or ":" in value
    ):
        raise StandingAuthorityError(f"{label} is invalid")
    return path


def _child_control_path(value: Any, label: str) -> tuple[Path, int]:
    if not isinstance(value, Path):
        raise StandingAuthorityError(f"{label} is invalid")
    path = _relative_path(value.as_posix(), label)
    match = _PROGRAM_CONTROL.fullmatch(path.name)
    if path.parent != Path("config/research") or match is None:
        raise StandingAuthorityError(f"{label} is outside the child-control namespace")
    return path, int(match.group("ordinal"))


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


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
