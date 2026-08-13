from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

import systematic_trading_lab.intraday_v3_freshness as freshness
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_v3_freshness import (
    IntradayV3FreshnessError,
    verify_intraday_v3_publication_seal,
)
from systematic_trading_lab.runtime_build import AttestationVerifierIdentity

_INVENTORY = Path("config/research/intraday-known-exposures-v1.json")
_SELECTION = Path("config/research/intraday-v3-period-selection-v2.json")
_PLAN = Path("config/research/intraday-campaign-v3.json")
_BINDING = Path("config/research/intraday-v3-qualification-binding-v1.json")
_COMMIT = "a" * 40
_FIRST_BAR = datetime(2026, 10, 1, 13, 30, tzinfo=UTC)

_SEAL_SPEC = importlib.util.spec_from_file_location(
    "write_intraday_v3_preregistration_seal",
    "scripts/write_intraday_v3_preregistration_seal.py",
)
assert _SEAL_SPEC is not None and _SEAL_SPEC.loader is not None
_SEAL_MODULE = importlib.util.module_from_spec(_SEAL_SPEC)
_SEAL_SPEC.loader.exec_module(_SEAL_MODULE)
build_seal: Callable[..., dict[str, object]] = _SEAL_MODULE.build_seal


def _write_seal(tmp_path: Path) -> Path:
    value = build_seal(_COMMIT, _INVENTORY, _SELECTION, _PLAN, _BINDING)
    path = tmp_path / "intraday-v3-preregistration-seal.json"
    path.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")
    return path


def _verification_output(seal: Path, timestamp: str) -> str:
    return json.dumps(
        [
            {
                "verificationResult": {
                    "statement": {
                        "subject": [
                            {
                                "name": seal.name,
                                "digest": {"sha256": hashlib.sha256(seal.read_bytes()).hexdigest()},
                            }
                        ]
                    },
                    "verifiedTimestamps": [
                        {
                            "type": "Tlog",
                            "uri": "https://rekor.sigstore.dev",
                            "timestamp": timestamp,
                        }
                    ],
                }
            }
        ]
    )


def test_trusted_main_attestation_establishes_cutoff(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    seal = _write_seal(tmp_path)
    verifier = AttestationVerifierIdentity("/trusted/gh", "2" * 64)
    monkeypatch.setattr(freshness, "_attestation_verifier_identity", lambda path: verifier)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, _verification_output(seal, "2026-09-01T00:00:00Z"), ""
        ),
    )

    result = verify_intraday_v3_publication_seal(
        seal, _INVENTORY, _SELECTION, _PLAN, _BINDING, verifier=verifier
    )

    assert result.witnessed_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert result.plan_fingerprint == json.loads(_PLAN.read_text())["plan_fingerprint"]


def test_missing_tlog_or_changed_selection_blocks_sealing(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    seal = _write_seal(tmp_path)
    verifier = AttestationVerifierIdentity("/trusted/gh", "2" * 64)
    monkeypatch.setattr(freshness, "_attestation_verifier_identity", lambda path: verifier)
    output = json.loads(_verification_output(seal, "2026-09-01T00:00:00Z"))
    output[0]["verificationResult"]["verifiedTimestamps"] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(output), ""),
    )
    with pytest.raises(IntradayV3FreshnessError):
        verify_intraday_v3_publication_seal(
            seal, _INVENTORY, _SELECTION, _PLAN, _BINDING, verifier=verifier
        )

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, _verification_output(seal, "2026-10-01T13:30:00Z"), ""
        ),
    )
    with pytest.raises(IntradayV3FreshnessError):
        verify_intraday_v3_publication_seal(
            seal, _INVENTORY, _SELECTION, _PLAN, _BINDING, verifier=verifier
        )

    selection = json.loads(_SELECTION.read_text())
    selection["periods"][1]["start"] = "2026-10-02"
    changed = tmp_path / _SELECTION.name
    changed.write_text(json.dumps(selection))
    with pytest.raises(IntradayV3FreshnessError):
        verify_intraday_v3_publication_seal(
            seal, _INVENTORY, changed, _PLAN, _BINDING, verifier=verifier
        )


def test_untrusted_local_timestamp_cannot_establish_cutoff(tmp_path: Path) -> None:
    seal = _write_seal(tmp_path)
    value = json.loads(seal.read_text())
    value["local_verified_at"] = "2026-08-13T00:00:00Z"
    unsigned = dict(value)
    unsigned.pop("seal_fingerprint")
    value["seal_fingerprint"] = fingerprint(unsigned)
    seal.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")

    with pytest.raises(IntradayV3FreshnessError):
        verify_intraday_v3_publication_seal(
            seal,
            _INVENTORY,
            _SELECTION,
            _PLAN,
            _BINDING,
            verifier=AttestationVerifierIdentity("/trusted/gh", "2" * 64),
        )


@pytest.mark.parametrize("mutation", ("authority", "foundation"))
def test_seal_cannot_change_authority_or_foundation(tmp_path: Path, mutation: str) -> None:
    seal = _write_seal(tmp_path)
    value = json.loads(seal.read_text())
    if mutation == "authority":
        value["authorities"]["broker_writes"] = True
    else:
        value["source_foundation_commit"] = "b" * 40
    unsigned = dict(value)
    unsigned.pop("seal_fingerprint")
    value["seal_fingerprint"] = fingerprint(unsigned)
    seal.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")

    with pytest.raises(IntradayV3FreshnessError):
        verify_intraday_v3_publication_seal(
            seal,
            _INVENTORY,
            _SELECTION,
            _PLAN,
            _BINDING,
            verifier=AttestationVerifierIdentity("/trusted/gh", "2" * 64),
        )
