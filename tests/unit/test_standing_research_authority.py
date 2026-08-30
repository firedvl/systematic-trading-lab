from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from systematic_trading_lab import standing_research_authority as authority
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]


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


def _standing_repository(root: Path) -> None:
    mandate_relative = authority.MANDATE_PATH
    for relative in authority.MANDATE_REVIEWED_SOURCE_PATHS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((_REPOSITORY / relative).read_bytes())
    mandate_path = root / mandate_relative
    mandate = json.loads(mandate_path.read_bytes())
    source_files = [
        {
            "path": relative.as_posix(),
            "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
        }
        for relative in authority.MANDATE_REVIEWED_SOURCE_PATHS
    ]
    _write(
        root / authority.MANDATE_REVIEW_PATH,
        {
            "schema_version": "standing-autonomous-research-mandate-independent-review-v1",
            "review_id": ("standing-autonomous-research-mandate-independent-review-2026-08-30-v1"),
            "status": "PASS-FINDING-FREE",
            "verdict": "PASS",
            "findings": [],
            "reviewed_mandate": _binding(root, mandate_relative, mandate["mandate_fingerprint"]),
            "reviewed_implementation": {
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "source_files": source_files,
                "implementation_root": fingerprint(source_files),
            },
            "challenge_results": [
                {"challenge": challenge, "verdict": "PASS"}
                for challenge in sorted(authority.MANDATE_REVIEW_CHALLENGES)
            ],
            "authority": _authority_flags(),
        },
        "review_fingerprint",
    )


def _child(root: Path, **updates: Any) -> tuple[Path, Path]:
    mandate = json.loads((root / authority.MANDATE_PATH).read_bytes())
    child_relative = Path("config/research/program-010-test-child-authority-v1.json")
    review_relative = Path("config/research/program-010-test-child-authority-review-v1.json")
    runtime_source_files = [
        {
            "path": mandate["source_grant"]["path"],
            "sha256": mandate["source_grant"]["sha256"],
        }
    ]
    unsigned: dict[str, Any] = {
        "schema_version": "standing-autonomous-research-child-authority-v1",
        "child_authority_id": authority.PROGRAM_010_CHILD_AUTHORITY_ID,
        "program_ordinal": 10,
        "program_id": "multi-hour-sector-etf-research-009",
        "operation_kind": authority.PROGRAM_010_CHILD_OPERATION_KIND,
        "status": "READY-FOR-STANDING-ACTIVATION",
        "one_use": True,
        "consumption_boundary": "immediately before first provider transport invocation",
        "standing_mandate": _binding(root, authority.MANDATE_PATH, mandate["mandate_fingerprint"]),
        "data_classes": ["FRESH-PROSPECTIVE-EXPOSED"],
        "bindings": {
            "frozen_source_grant": {
                "path": mandate["source_grant"]["path"],
                "sha256": mandate["source_grant"]["sha256"],
            }
        },
        "runtime_binding": {
            "source_commit": "c" * 40,
            "source_tree": "d" * 40,
            "source_files": runtime_source_files,
            "implementation_root": fingerprint(runtime_source_files),
        },
        "required_review_challenges": list(authority.PROGRAM_010_CHILD_REVIEW_CHALLENGES),
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
            "review_id": "test-program-010-source-qualification-child-review-v1",
            "status": "PASS-FINDING-FREE",
            "verdict": "PASS",
            "findings": [],
            "reviewed_child_authority": _binding(
                root, child_relative, child["child_authority_fingerprint"]
            ),
            "challenge_results": [
                {"challenge": challenge, "verdict": "PASS"}
                for challenge in authority.PROGRAM_010_CHILD_REVIEW_CHALLENGES
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


def test_reviewed_child_derives_stable_identity_without_external_root(tmp_path: Path) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path)

    first = authority.derive_child_identity(tmp_path, child_path, review_path)
    second = authority.derive_child_identity(tmp_path, child_path, review_path)

    assert first == second
    assert first["status"] == "REVIEWED-READY-FOR-RUNTIME-ACTIVATION"
    assert first["external_authorization_root_required"] is False
    assert first["runtime_revalidation_required_before_active_state"] is True
    assert first["standing_mandate_review"]["path"] == authority.MANDATE_REVIEW_PATH.as_posix()
    assert first["authority"] == _authority_flags(
        "provider_contact", "credential_access", "source_requests", "source_qualification"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"program_ordinal": 9},
        {"data_classes": ["CONTROLLED"]},
        {"authority": _authority_flags("paper_execution")},
        {"operation_kind": "ARBITRARY-OPERATION"},
    ],
)
def test_child_cannot_reach_history_or_forbidden_scope(
    tmp_path: Path, updates: dict[str, Any]
) -> None:
    _standing_repository(tmp_path)
    child_path, review_path = _child(tmp_path, **updates)

    with pytest.raises(authority.StandingAuthorityError, match="exceeds the standing mandate"):
        authority.derive_child_identity(tmp_path, child_path, review_path)


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
