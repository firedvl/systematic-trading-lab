"""Prospective V3 freshness and trusted GitHub/main publication evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import non_broker_subprocess_environment
from .fingerprints import fingerprint
from .intraday_exposure import (
    parse_intraday_exposure_inventory,
    parse_intraday_v3_period_selection,
)
from .intraday_v3_campaign import parse_intraday_v3_campaign_plan
from .intraday_v3_qualification import load_intraday_v3_qualification_binding
from .runtime_build import (
    AttestationVerifierIdentity,
    RuntimeBuildAttestationIndeterminateError,
    _attestation_verifier_identity,
    _resolve_attestation_verifier,
)

_REPOSITORY = "firedvl/systematic-trading-lab"
_WORKFLOW = ".github/workflows/build-provenance.yml"
_SOURCE_REF = "refs/heads/main"
_FOUNDATION_COMMIT = "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723"
_AUTHORITIES = {
    "research_qualification": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_TRANSIENT_FAILURES = (
    "connection refused",
    "connection reset",
    "could not resolve host",
    "i/o timeout",
    "network is unreachable",
    "rate limit exceeded",
    "temporary failure in name resolution",
    "tls handshake timeout",
)


class IntradayV3FreshnessError(RuntimeError):
    """Prospective freshness or its trusted publication proof failed closed."""


@dataclass(frozen=True)
class IntradayV3PublicationSeal:
    source_commit: str
    inventory_fingerprint: str
    selection_fingerprint: str
    plan_fingerprint: str
    qualification_binding_fingerprint: str
    first_validation_bar: datetime
    witnessed_at: datetime
    seal_fingerprint: str
    seal_sha256: str
    verifier: AttestationVerifierIdentity

    @property
    def publication_fingerprint(self) -> str:
        return fingerprint(self)


def verify_intraday_v3_publication_seal(
    seal: Path,
    inventory: Path,
    selection: Path,
    plan: Path,
    qualification_binding: Path,
    *,
    verifier: AttestationVerifierIdentity | None = None,
) -> IntradayV3PublicationSeal:
    """Verify exact main provenance and use only a signed Tlog timestamp as trusted time."""

    try:
        raw = seal.read_bytes()
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "source_repository",
            "signer_workflow",
            "source_commit",
            "source_foundation_commit",
            "first_validation_bar",
            "freshness_basis",
            "universal_freshness_proven",
            "prospective_market_data_freshness",
            "artifacts",
            "authorities",
            "seal_fingerprint",
        }:
            raise ValueError("V3 publication seal fields differ")
        unsigned = dict(value)
        claimed = unsigned.pop("seal_fingerprint")
        if (
            value["schema_version"] != "intraday-v3-preregistration-seal-v1"
            or value["source_repository"] != _REPOSITORY
            or value["signer_workflow"] != _WORKFLOW
            or value["freshness_basis"] != "main-attested-design-before-first-market-bar-v1"
            or value["universal_freshness_proven"] is not False
            or value["prospective_market_data_freshness"] is not True
            or value["source_foundation_commit"] != _FOUNDATION_COMMIT
            or value["authorities"] != _AUTHORITIES
            or not isinstance(claimed, str)
            or fingerprint(unsigned) != claimed
        ):
            raise ValueError("V3 publication seal identity differs")
        source_commit = _hex(value["source_commit"], 40, "source commit")
        first_bar = _utc(value["first_validation_bar"], "first validation bar")
        artifacts = value["artifacts"]
        expected = {
            "exposure_inventory": (inventory, "inventory_fingerprint"),
            "period_selection": (selection, "selection_fingerprint"),
            "campaign_plan": (plan, "plan_fingerprint"),
            "qualification_binding": (qualification_binding, "binding_fingerprint"),
        }
        if not isinstance(artifacts, Mapping) or set(artifacts) != set(expected):
            raise ValueError("V3 publication artifact set differs")
        identities: dict[str, str] = {}
        artifact_values: dict[str, object] = {}
        for role, (path, field) in expected.items():
            entry = artifacts[role]
            if not isinstance(entry, Mapping) or set(entry) != {"path", "sha256", "fingerprint"}:
                raise ValueError("V3 publication artifact identity differs")
            contents = path.read_bytes()
            artifact = json.loads(contents, object_pairs_hook=_unique_object)
            artifact_unsigned = dict(artifact) if isinstance(artifact, Mapping) else {}
            artifact_claimed = artifact_unsigned.pop(field, None)
            if (
                entry["path"] != path.as_posix()
                or entry["sha256"] != hashlib.sha256(contents).hexdigest()
                or not isinstance(artifact, Mapping)
                or not isinstance(artifact_claimed, str)
                or entry["fingerprint"] != artifact_claimed
                or fingerprint(artifact_unsigned) != artifact_claimed
            ):
                raise ValueError("V3 publication artifact differs from seal")
            identities[role] = str(entry["fingerprint"])
            artifact_values[role] = artifact
        parsed_inventory = parse_intraday_exposure_inventory(artifact_values["exposure_inventory"])
        parsed_selection = parse_intraday_v3_period_selection(
            artifact_values["period_selection"], parsed_inventory
        )
        parsed_plan = parse_intraday_v3_campaign_plan(artifact_values["campaign_plan"])
        parsed_binding = load_intraday_v3_qualification_binding(qualification_binding)
        planned = parsed_plan.payload
        prospective = planned.get("prospective_freshness")
        trusted_time = planned.get("trusted_time_policy")
        if (
            not isinstance(prospective, Mapping)
            or not isinstance(trusted_time, Mapping)
            or parsed_selection.inventory_fingerprint != identities["exposure_inventory"]
            or prospective.get("period_selection_fingerprint") != identities["period_selection"]
            or parsed_binding.fingerprint != identities["qualification_binding"]
            or parsed_plan.source_foundation_commit != value["source_foundation_commit"]
            or planned.get("authorities") != value["authorities"]
            or trusted_time.get("first_validation_bar") != value["first_validation_bar"]
            or parsed_selection.periods[1].start_timestamp != first_bar
        ):
            raise ValueError("V3 sealed design links differ")
        verifier = verifier or _resolve_attestation_verifier()
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory, seal.name)
            snapshot.write_bytes(raw)
            witnessed_at = _verify_attestation_time(snapshot, source_commit, verifier)
        if witnessed_at >= first_bar:
            raise ValueError("V3 publication was not witnessed before its first validation bar")
        return IntradayV3PublicationSeal(
            source_commit,
            identities["exposure_inventory"],
            identities["period_selection"],
            identities["campaign_plan"],
            identities["qualification_binding"],
            first_bar,
            witnessed_at,
            claimed,
            hashlib.sha256(raw).hexdigest(),
            verifier,
        )
    except IntradayV3FreshnessError:
        raise
    except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise IntradayV3FreshnessError("V3 publication seal verification failed") from error


def _verify_attestation_time(
    path: Path, source_commit: str, verifier: AttestationVerifierIdentity
) -> datetime:
    try:
        verifier_path = Path(verifier.path)
        if _attestation_verifier_identity(verifier_path) != verifier:
            raise ValueError("attestation verifier differs before verification")
        completed = subprocess.run(
            [
                verifier.path,
                "attestation",
                "verify",
                str(path),
                "--repo",
                _REPOSITORY,
                "--hostname",
                "github.com",
                "--signer-workflow",
                f"{_REPOSITORY}/{_WORKFLOW}",
                "--source-ref",
                _SOURCE_REF,
                "--source-digest",
                source_commit,
                "--deny-self-hosted-runners",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            env=non_broker_subprocess_environment(),
            text=True,
            timeout=30,
        )
        if _attestation_verifier_identity(verifier_path) != verifier:
            raise ValueError("attestation verifier changed during verification")
        results = json.loads(completed.stdout, object_pairs_hook=_unique_object)
        if not isinstance(results, list) or not results:
            raise ValueError("V3 attestation verification returned no result")
        seal_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        timestamps: list[datetime] = []
        for result in results:
            verification = result.get("verificationResult") if isinstance(result, Mapping) else None
            statement = verification.get("statement") if isinstance(verification, Mapping) else None
            subjects = statement.get("subject") if isinstance(statement, Mapping) else None
            if not isinstance(subjects, list) or not any(
                isinstance(subject, Mapping)
                and subject.get("name") == path.name
                and isinstance(subject.get("digest"), Mapping)
                and subject["digest"].get("sha256") == seal_digest
                for subject in subjects
            ):
                continue
            assert isinstance(verification, Mapping)
            verified = verification.get("verifiedTimestamps")
            if not isinstance(verified, list):
                continue
            timestamps.extend(
                _utc(item.get("timestamp"), "verified transparency-log timestamp")
                for item in verified
                if isinstance(item, Mapping) and item.get("type") == "Tlog"
            )
        if not timestamps:
            raise ValueError("V3 attestation has no verified transparency-log timestamp")
        return min(timestamps)
    except subprocess.TimeoutExpired as error:
        raise RuntimeBuildAttestationIndeterminateError(
            "V3 publication attestation verdict is indeterminate"
        ) from error
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.lower() if isinstance(error.stderr, str) else ""
        if error.returncode == 1 and (
            any(message in stderr for message in _TRANSIENT_FAILURES)
            or any(f"http {status}" in stderr for status in (429, 500, 502, 503, 504))
        ):
            raise RuntimeBuildAttestationIndeterminateError(
                "V3 publication attestation verdict is indeterminate"
            ) from error
        raise IntradayV3FreshnessError("V3 publication attestation failed") from error
    except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise IntradayV3FreshnessError("V3 publication attestation failed") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("V3 publication evidence contains duplicate fields")
    return value


def _hex(value: object, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"V3 {label} is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"V3 {label} must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"V3 {label} must be UTC")
    return parsed
