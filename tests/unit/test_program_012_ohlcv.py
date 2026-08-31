from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab import program_012_ohlcv as program_012
from systematic_trading_lab.program_007_alpaca import RawBar

_REPOSITORY = Path(__file__).resolve().parents[2]
_PROPOSAL_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-structural-admission-proposal-v3.json"
)
_PROGRAM_005_PATH = Path("config/research/program-005-free-alpaca-successor-plan-v1.json")
_INCIDENT_PATH = Path(
    "config/research/program-002-exposed-acquisition-completeness-failure-v3.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_bytes()))


def _contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return _load(_PROPOSAL_PATH), _load(_PROGRAM_005_PATH), _load(_INCIDENT_PATH)


def _morning_metrics() -> dict[date, dict[str, tuple[Decimal, Decimal, Decimal]]]:
    fixed = set(program_012.FIXED_QUARANTINE)
    sessions = sorted(program_012.full_trade_sessions())
    midpoint = Decimal(sessions[len(sessions) // 2].toordinal())
    return {
        session: {symbol: (value, value, value) for symbol in ("SPY", "MDY")}
        for session in sessions
        for value in (midpoint if session in fixed else Decimal(session.toordinal()),)
    }


def test_request_and_incident_inventories_match_the_frozen_contract() -> None:
    _, program_005, incident = _contracts()
    requests = program_012.acquisition_requests()

    assert len(requests) == program_012.EXPECTED_SESSION_COUNT
    assert requests[0].session == program_012.CONTEXT_START
    assert requests[-1].session == program_012.EXPOSED_END
    assert sum(len(request.expected_coordinates) for request in requests) == (
        program_012.EXPECTED_COORDINATE_COUNT
    )
    assert program_012.derive_incident_inventory(incident, program_005) == tuple(
        program_005["source_qualification"]["known_mdy_coordinates"]
    )


def test_one_isolated_nonquarantine_full_session_loss_passes() -> None:
    proposal, program_005, incident = _contracts()
    session = date(2024, 6, 3)
    missing = {session: {"SPY@2024-06-03T13:30:00Z"}}

    report = program_012.assess_structural_admission(
        proposal, program_005, incident, missing, _morning_metrics()
    )

    assert report["admission_passed"] is True
    assert report["status"] == "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX"
    assert report["unexpected_excluded_sessions"] == [session.isoformat()]


def test_extra_coordinate_on_a_fixed_quarantine_session_fails() -> None:
    proposal, program_005, incident = _contracts()
    inventory = program_012.derive_incident_inventory(incident, program_005)
    missing = {
        date(2020, 12, 4): {
            *(value for value in inventory if value.startswith("MDY@2020-12-04")),
            "SPY@2020-12-04T14:30:00Z",
        }
    }

    report = program_012.assess_structural_admission(
        proposal, program_005, incident, missing, _morning_metrics()
    )

    assert report["admission_passed"] is False
    assert report["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert "quarantine-unexpected-coordinate" in report["failures"]


def test_morning_metrics_require_the_exact_frozen_window() -> None:
    request = program_012.acquisition_requests()[0]
    rows = [
        RawBar(
            "SPY",
            timestamp,
            Decimal(100),
            Decimal(101),
            Decimal(99),
            Decimal(100),
            Decimal(10),
        )
        for timestamp in request.grid[:25]
        if timestamp != request.grid[1]
    ]
    output: dict[date, dict[str, tuple[Decimal, Decimal, Decimal]]] = {}

    program_012.collect_morning_metrics(rows, output)

    assert output == {}
