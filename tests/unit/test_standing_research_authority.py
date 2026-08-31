from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from systematic_trading_lab import standing_research_authority as authority
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_RUNTIME_ENTRYPOINT = Path("src/systematic_trading_lab/program_010_ohlcv.py")


def _write(path: Path, unsigned: dict[str, Any], fingerprint_field: str) -> dict[str, Any]:
    payload = {**unsigned, fingerprint_field: fingerprint(unsigned)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _binding(root: Path, relative: Path, fingerprint_value: str) -> dict[str, str]:
    raw = (root / relative).read_bytes()
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprint": fingerprint_value,
    }


def _authority_flags(*enabled: str) -> dict[str, bool]:
    return {field: field in enabled for field in authority.AUTHORITY_FIELDS}


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(root: Path, message: str, *paths: Path) -> tuple[str, str]:
    _git(root, "add", "--", *(path.as_posix() for path in paths))
    _git(root, "commit", "--quiet", "-m", message)
    commit = _git(root, "rev-parse", "HEAD")
    return commit, _git(root, "rev-parse", f"{commit}^{{tree}}")


def _source_binding(root: Path, commit: str, tree: str, paths: tuple[Path, ...]) -> dict[str, Any]:
    source_files = [
        {
            "path": path.as_posix(),
            "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest(),
        }
        for path in paths
    ]
    return {
        "source_commit": commit,
        "source_tree": tree,
        "source_files": source_files,
        "implementation_root": fingerprint(source_files),
    }


def _standing_repository(root: Path) -> None:
    copied_paths = (*authority.MANDATE_REVIEWED_SOURCE_PATHS, _RUNTIME_ENTRYPOINT)
    for relative in copied_paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((_REPOSITORY / relative).read_bytes())
    _git(root, "init", "--quiet")
    _git(root, "config", "user.name", "Standing Authority Test")
    _git(root, "config", "user.email", "standing-authority-test@example.invalid")
    commit, tree = _commit(root, "record standing controls", *copied_paths)

    mandate_relative = authority.MANDATE_PATH
    mandate = json.loads((root / mandate_relative).read_bytes())
    _write(
        root / authority.MANDATE_REVIEW_PATH,
        {
            "schema_version": "standing-autonomous-research-mandate-independent-review-v1",
            "review_id": ("standing-autonomous-research-mandate-independent-review-2026-08-30-v1"),
            "status": "PASS-FINDING-FREE",
            "verdict": "PASS",
            "findings": [],
            "reviewed_mandate": _binding(root, mandate_relative, mandate["mandate_fingerprint"]),
            "reviewed_implementation": _source_binding(
                root, commit, tree, authority.MANDATE_REVIEWED_SOURCE_PATHS
            ),
            "challenge_results": [
                {"challenge": challenge, "verdict": "PASS"}
                for challenge in sorted(authority.MANDATE_REVIEW_CHALLENGES)
            ],
            "authority": _authority_flags(),
        },
        "review_fingerprint",
    )


def _child(root: Path, program_ordinal: int = 10, **updates: Any) -> tuple[Path, Path]:
    mandate = json.loads((root / authority.MANDATE_PATH).read_bytes())
    prefix = f"program-{program_ordinal:03d}"
    manifest_relative = Path(f"config/research/{prefix}-test-operation-manifest-v1.json")
    child_relative = Path(f"config/research/{prefix}-test-child-authority-v1.json")
    review_relative = Path(f"config/research/{prefix}-test-child-authority-review-v1.json")
    manifest = _write(
        root / manifest_relative,
        {
            "schema_version": "test-fixed-get-operation-manifest-v1",
            "method": "GET",
            "endpoint": "https://data.example.invalid/v2/stocks/bars",
            "maximum_requests": 16,
            "private_evidence_root": ".trading-lab/test-child",
        },
        "operation_manifest_fingerprint",
    )
    commit, tree = _commit(root, "freeze child operation", manifest_relative)
    runtime_paths = (_RUNTIME_ENTRYPOINT, manifest_relative)
    required_challenges = sorted(authority.CHILD_REVIEW_REQUIRED_CHALLENGES)
    unsigned: dict[str, Any] = {
        "schema_version": "standing-autonomous-research-child-authority-v1",
        "child_authority_id": f"{prefix}-test-child-authority-v1",
        "program_ordinal": program_ordinal,
        "program_id": "multi-hour-sector-etf-research-009",
        "operation_kind": "TEST-FIXED-GET-SOURCE-QUALIFICATION",
        "status": "PROSPECTIVE-CHILD-CONTROL",
        "one_use": True,
        "consumption_boundary": "immediately before first provider transport invocation",
        "concrete_runtime_validation_required": True,
        "runtime_revalidation_required": True,
        "atomic_one_use_claim_required": True,
        "terminal_evidence_required": True,
        "standing_mandate": _binding(root, authority.MANDATE_PATH, mandate["mandate_fingerprint"]),
        "data_classes": ["FRESH-PROSPECTIVE-EXPOSED"],
        "operation_manifest": _binding(
            root, manifest_relative, manifest["operation_manifest_fingerprint"]
        ),
        "runtime_entrypoint": _RUNTIME_ENTRYPOINT.as_posix(),
        "runtime_binding": _source_binding(root, commit, tree, runtime_paths),
        "required_review_challenges": required_challenges,
        "authority": _authority_flags(
            "provider_contact", "credential_access", "source_requests", "source_qualification"
        ),
    }
    unsigned.update(updates)
    child = _write(root / child_relative, unsigned, "child_authority_fingerprint")
    _write(
        root / review_relative,
        {
            "schema_version": (
                "standing-autonomous-research-child-authority-independent-review-v1"
            ),
            "review_id": f"test-{prefix}-source-qualification-child-review-v1",
            "status": "PASS-FINDING-FREE",
            "verdict": "PASS",
            "findings": [],
            "reviewed_child_authority": _binding(
                root, child_relative, child["child_authority_fingerprint"]
            ),
            "challenge_results": [
                {"challenge": challenge, "verdict": "PASS"}
                for challenge in unsigned["required_review_challenges"]
            ],
            "authority": _authority_flags(),
        },
        "review_fingerprint",
    )
    return child_relative, review_relative


@pytest.mark.skipif(
    not (_REPOSITORY / authority.MANDATE_REVIEW_PATH).exists(),
    reason="independent review is added after the reviewed source commit",
)
def test_committed_standing_mandate_is_exact_and_reviewed() -> None:
    mandate = authority.load_standing_mandate(_REPOSITORY)

    assert mandate["mandate_fingerprint"] == authority.MANDATE_FINGERPRINT
    assert mandate["source_grant"]["exact_user_bytes_committed"] is True
    assert mandate["activation_contract"]["minimum_program_ordinal"] == 10
    assert all(
        mandate["authority"][field] is False for field in authority.FORBIDDEN_CHILD_AUTHORITY
    )


def test_reviewed_child_derives_nonactivating_identity_without_external_root(
    tmp_path: Path,
) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path)

    first = authority.derive_child_identity(tmp_path, child_path, review_path)
    second = authority.derive_child_identity(tmp_path, child_path, review_path)

    assert first == second
    assert first["status"] == "REVIEWED-CONTROL-IDENTITY"
    assert first["external_authorization_root_required"] is False
    assert first["runtime_activation_authorized"] is False
    assert first["concrete_runtime_validation_required"] is True
    assert first["atomic_one_use_claim_required"] is True
    assert first["terminal_evidence_required"] is True
    assert first["runtime_entrypoint"] == _RUNTIME_ENTRYPOINT.as_posix()


def test_later_program_uses_the_same_standing_control(tmp_path: Path) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(
        tmp_path,
        program_ordinal=11,
        child_authority_id="program-011-successor-child-authority-v1",
        program_id="multi-hour-sector-etf-research-010",
        operation_kind="SUCCESSOR-EXPOSED-SOURCE-QUALIFICATION",
    )

    identity = authority.derive_child_identity(tmp_path, child_path, review_path)

    assert identity["program_ordinal"] == 11
    assert identity["operation_kind"] == "SUCCESSOR-EXPOSED-SOURCE-QUALIFICATION"


@pytest.mark.parametrize(
    "updates",
    [
        {"program_ordinal": 9},
        {"data_classes": ["CONTROLLED"]},
        {"authority": _authority_flags("paper_execution")},
        {"operation_kind": ""},
        {"atomic_one_use_claim_required": False},
    ],
)
def test_child_cannot_reach_history_or_forbidden_scope(
    tmp_path: Path, updates: dict[str, Any]
) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path, **updates)

    with pytest.raises(authority.StandingAuthorityError, match="exceeds the standing mandate"):
        authority.derive_child_identity(tmp_path, child_path, review_path)


def test_operation_manifest_change_after_review_fails_closed(tmp_path: Path) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path)
    child = json.loads((tmp_path / child_path).read_bytes())
    manifest_path = tmp_path / child["operation_manifest"]["path"]
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")

    with pytest.raises(authority.StandingAuthorityError, match="bound child artifact differs"):
        authority.derive_child_identity(tmp_path, child_path, review_path)


def test_runtime_source_change_after_review_fails_closed(tmp_path: Path) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path)
    runtime_path = tmp_path / _RUNTIME_ENTRYPOINT
    runtime_path.write_bytes(runtime_path.read_bytes() + b"\n")

    with pytest.raises(authority.StandingAuthorityError, match="differs from its Git tree"):
        authority.derive_child_identity(tmp_path, child_path, review_path)


@pytest.mark.parametrize("field", ["source_commit", "source_tree"])
def test_mandate_review_must_bind_real_git_objects(tmp_path: Path, field: str) -> None:
    _standing_repository(tmp_path)
    review_path = tmp_path / authority.MANDATE_REVIEW_PATH
    review = json.loads(review_path.read_bytes())
    review["reviewed_implementation"][field] = "a" * 40
    unsigned = {key: value for key, value in review.items() if key != "review_fingerprint"}
    _write(review_path, unsigned, "review_fingerprint")

    with pytest.raises(authority.StandingAuthorityError, match="Git provenance"):
        authority.load_standing_mandate(tmp_path)


def test_mandate_review_hashes_must_match_the_reviewed_tree(tmp_path: Path) -> None:
    _standing_repository(tmp_path)
    review_path = tmp_path / authority.MANDATE_REVIEW_PATH
    review = json.loads(review_path.read_bytes())
    source_files = review["reviewed_implementation"]["source_files"]
    source_files[0]["sha256"] = "0" * 64
    review["reviewed_implementation"]["implementation_root"] = fingerprint(source_files)
    unsigned = {key: value for key, value in review.items() if key != "review_fingerprint"}
    _write(review_path, unsigned, "review_fingerprint")

    with pytest.raises(authority.StandingAuthorityError, match="differs from its Git tree"):
        authority.load_standing_mandate(tmp_path)


def test_child_change_after_review_fails_closed(tmp_path: Path) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path)
    child = json.loads((tmp_path / child_path).read_bytes())
    child["consumption_boundary"] = "different pre-transport boundary"
    unsigned = {key: value for key, value in child.items() if key != "child_authority_fingerprint"}
    _write(tmp_path / child_path, unsigned, "child_authority_fingerprint")

    with pytest.raises(authority.StandingAuthorityError, match="review semantics differ"):
        authority.derive_child_identity(tmp_path, child_path, review_path)


@pytest.mark.parametrize(
    "bad_path",
    [Path("../program-010-child.json"), Path("/tmp/program-010-child.json")],
)
def test_child_control_path_cannot_escape_repository(tmp_path: Path, bad_path: Path) -> None:
    _standing_repository(tmp_path)
    _, review_path = _child(tmp_path)

    with pytest.raises(authority.StandingAuthorityError, match="path is"):
        authority.derive_child_identity(tmp_path, bad_path, review_path)


def test_incomplete_child_review_challenges_fail_closed(tmp_path: Path) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path)
    review = json.loads((tmp_path / review_path).read_bytes())
    review["challenge_results"] = review["challenge_results"][:1]
    unsigned = {key: value for key, value in review.items() if key != "review_fingerprint"}
    _write(tmp_path / review_path, unsigned, "review_fingerprint")

    with pytest.raises(authority.StandingAuthorityError, match="review semantics differ"):
        authority.derive_child_identity(tmp_path, child_path, review_path)
