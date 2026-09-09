import hashlib
import json
from pathlib import Path

from systematic_trading_lab.fingerprints import fingerprint


def test_invalid_terminal_review_cannot_claim_pass_and_preserves_terminal() -> None:
    root = Path(__file__).resolve().parents[2]
    review = json.loads(
        (
            root
            / "config/research/program-019-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-terminal-result-independent-review-v1.json"
        ).read_text()
    )
    assert review.pop("review_fingerprint") == fingerprint(review)
    assert review["status"] == "INVALID-NOT-INDEPENDENTLY-REVIEWED"
    assert review["verdict"] == "INVALID"
    assert review["findings"]
    assert review["challenge_results"] == []
    assert review["withdrawal"]["independent_terminal_review_completed"] is False
    assert review["withdrawal"]["successor_gate_satisfied"] is False
    assert all(value is False for value in review["authority"].values())
    terminal = root / review["reviewed_public_terminal"]["path"]
    assert hashlib.sha256(terminal.read_bytes()).hexdigest() == (
        "52c9919b1b1d93e256b8e8b2bd9848476905af6141991bf5d5d45bcade34154c"
    )
