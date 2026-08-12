"""Fail-closed runtime configuration."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from .domain import TradingMode
from .fingerprints import fingerprint


class ConfigurationError(ValueError):
    pass


_DOTENV_KEYS = {
    "TRADING_LAB_MODE",
    "TRADING_LAB_HOME",
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "TRADING_LAB_PAPER_ACTIVATION_ID",
    "TRADING_LAB_PAPER_CODE_COMMIT",
}
_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class PaperWriteRequest:
    activation_id: str
    code_commit: str

    def __post_init__(self) -> None:
        if len(self.activation_id) != 64 or any(
            character not in "0123456789abcdef" for character in self.activation_id
        ):
            raise ConfigurationError("paper activation ID must be a SHA-256 fingerprint")
        if len(self.code_commit) != 40 or any(
            character not in "0123456789abcdef" for character in self.code_commit
        ):
            raise ConfigurationError("paper code commit must be a full lowercase Git SHA-1")

    @property
    def request_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class Settings:
    mode: TradingMode
    home: Path
    paper_write_request: PaperWriteRequest | None = None

    @property
    def broker_writes_allowed(self) -> bool:
        return self.mode is TradingMode.PAPER and self.paper_write_request is not None


def load_dotenv(
    path: Path | None = None, environment: MutableMapping[str, str] | None = None
) -> None:
    """Load supported local settings without overriding the process environment."""
    source = path or Path.cwd() / ".env"
    target = os.environ if environment is None else environment
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ConfigurationError(f"cannot read environment file: {source}") from error
    names: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, raw_value = stripped.partition("=")
        if not separator or not _ENVIRONMENT_NAME.fullmatch(name) or name not in _DOTENV_KEYS:
            raise ConfigurationError(f"invalid .env entry at line {line_number}")
        if name in names:
            raise ConfigurationError(f"duplicate .env entry at line {line_number}")
        names.add(name)
        value = raw_value.strip()
        if value[:1] in {'"', "'"} or value[-1:] in {'"', "'"}:
            if len(value) < 2 or value[0] != value[-1]:
                raise ConfigurationError(f"invalid quoted .env value at line {line_number}")
            value = value[1:-1]
        target.setdefault(name, value)


def load_settings(environment: Mapping[str, str] | None = None) -> Settings:
    values = os.environ if environment is None else environment
    raw_mode = values.get("TRADING_LAB_MODE", TradingMode.OFFLINE.value).strip()
    if raw_mode == "live":
        raise ConfigurationError("live trading is disabled by repository policy")
    try:
        mode = TradingMode(raw_mode)
    except ValueError as error:
        raise ConfigurationError(f"invalid TRADING_LAB_MODE: {raw_mode!r}") from error
    raw_home = values.get("TRADING_LAB_HOME", ".trading-lab").strip()
    if not raw_home:
        raise ConfigurationError("TRADING_LAB_HOME must not be empty")
    activation_id = values.get("TRADING_LAB_PAPER_ACTIVATION_ID", "").strip()
    code_commit = values.get("TRADING_LAB_PAPER_CODE_COMMIT", "").strip()
    if bool(activation_id) != bool(code_commit):
        raise ConfigurationError("paper write opt-in requires activation ID and code commit")
    if activation_id and mode is not TradingMode.PAPER:
        raise ConfigurationError("paper write opt-in requires paper mode")
    request = None if not activation_id else PaperWriteRequest(activation_id, code_commit)
    return Settings(
        mode=mode,
        home=Path(raw_home).expanduser().resolve(),
        paper_write_request=request,
    )


def non_broker_subprocess_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy an environment without broker credentials or write opt-in."""
    values = os.environ if environment is None else environment
    return {
        name: value
        for name, value in values.items()
        if not name.startswith(("APCA_", "TRADING_LAB_PAPER_"))
    }
