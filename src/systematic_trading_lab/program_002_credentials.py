"""Program 002 acquisition credential boundary."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping

ACQUISITION_CREDENTIAL_NAMES = (
    "PROGRAM_002_ACQUISITION_API_KEY_ID",
    "PROGRAM_002_ACQUISITION_API_SECRET_KEY",
)
ACCOUNT_ENVIRONMENT_NAME = "PROGRAM_002_ACQUISITION_ACCOUNT_ENVIRONMENT"
_RESEARCH_FORBIDDEN_MARKERS = ("APCA", "ALPACA", "BROKER", "IBKR")
MASSIVE_CREDENTIAL_NAME = "PROGRAM_002_MASSIVE_API_KEY"


def read_acquisition_credentials(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    env = os.environ if environ is None else environ
    allowed = {*ACQUISITION_CREDENTIAL_NAMES, ACCOUNT_ENVIRONMENT_NAME}
    forbidden = ("APCA", "ALPACA", "BROKER", "IBKR", "PAPER", "LIVE")
    if any(
        value
        and key not in allowed
        and (
            key.upper().startswith("PROGRAM_002_ACQUISITION_")
            or any(marker in key.upper() for marker in forbidden)
        )
        for key, value in env.items()
    ):
        raise ValueError("non-acquisition credentials are present")
    key, secret = (env.get(name, "") for name in ACQUISITION_CREDENTIAL_NAMES)
    if not key or not secret:
        raise ValueError("Program 002 acquisition credentials are required")
    return key, secret


def acquisition_account_environment(environ: Mapping[str, str] | None = None) -> str:
    value = (os.environ if environ is None else environ).get(ACCOUNT_ENVIRONMENT_NAME, "")
    if value not in {"paper", "live"}:
        raise ValueError(f"{ACCOUNT_ENVIRONMENT_NAME} must be paper or live")
    return value


def credential_key_id_hash(key_id: str) -> str:
    return hashlib.sha256(key_id.encode()).hexdigest()


def reject_research_credentials(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    present = sorted(
        key
        for key, value in env.items()
        if value
        and (
            (normalized := key.upper()).startswith("PROGRAM_002_ACQUISITION_")
            or normalized == MASSIVE_CREDENTIAL_NAME
            or any(marker in normalized for marker in _RESEARCH_FORBIDDEN_MARKERS)
            or normalized.startswith(("PAPER", "LIVE"))
            or "_PAPER" in normalized
            or "_LIVE" in normalized
        )
    )
    if present:
        raise ValueError(f"Program 002 research runtime forbids credentials: {', '.join(present)}")
