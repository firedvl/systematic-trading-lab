import hashlib
import json
from pathlib import Path

from systematic_trading_lab.fingerprints import fingerprint


def test_invalid_terminal_review_cannot_claim_pass_and_preserves_terminal() -> None:
    root = Path(__file__).resolve().parents[2]
    review = json.loads(
        (
            root
            / (
                "config/research/program-019-exposed-prefix-raw-alpaca-sip-recovery-and-"
                "structural-admission-terminal-result-independent-review-v1.json"
            )
        ).read_text()
    )
    assert review.pop("review_fingerprint") == fingerprint(review)
    assert review["status"] == "INVALID-NOT-INDEPENDENTLY-REVIEWED"
    assert review["verdict"] == "INVALID"
    assert review["findings"]
    assert review["challenge_results"] == []
    assert review["withdrawal"]["independent_terminal_review_completed"] is False
    assert review["withdrawal"]["successor_gate_satisfied"] is False
    assert review["withdrawal"]["public_terminal_unchanged"] is True
    assert review["withdrawal"]["private_evidence_integrity_independently_verified"] is False
    assert review["withdrawal"]["private_evidence_accessed_during_withdrawal_review"] is False
    assert all(value is False for value in review["authority"].values())
    terminal = root / review["reviewed_public_terminal"]["path"]
    assert hashlib.sha256(terminal.read_bytes()).hexdigest() == (
        "52c9919b1b1d93e256b8e8b2bd9848476905af6141991bf5d5d45bcade34154c"
    )


def test_genuine_terminal_review_is_separate_and_binds_preserved_failure() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / (
        "config/research/program-019-exposed-prefix-raw-alpaca-sip-recovery-and-"
        "structural-admission-terminal-result-independent-review-v2.json"
    )
    review = json.loads(path.read_text())
    assert review.pop("review_fingerprint") == fingerprint(review)
    assert review["status"] == "PASS-TERMINAL-FAILURE-VERIFIED"
    assert review["verdict"] == "PASS" and review["findings"] == []
    assert review["review_provenance"]["withdrawn_v1_used_as_evidence"] is False
    assert review["review_provenance"]["fresh_context"] is True
    assert review["verification"]["full_read_only_chain_validator"] == {
        "exit_status": 0,
        "result": "PASS",
    }
    binding = review["reviewed_public_terminal"]
    assert hashlib.sha256((root / binding["path"]).read_bytes()).hexdigest() == binding["sha256"]
    assert binding["status"] == "FAIL-CONSUMED-NO-RETRY"
    assert binding["admission_passed"] is False
    assert all(value is False for value in review["effective_final_authority"].values())
