"""Fail-closed runtime configuration."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from .domain import TradingMode


class ConfigurationError(ValueError):
    pass


_DOTENV_KEYS = {
    "TRADING_LAB_MODE",
    "TRADING_LAB_HOME",
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
}
_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class Settings:
    mode: TradingMode
    home: Path

    @property
    def broker_writes_allowed(self) -> bool:
        return False


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
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, raw_value = stripped.partition("=")
        if not separator or not _ENVIRONMENT_NAME.fullmatch(name) or name not in _DOTENV_KEYS:
            raise ConfigurationError(f"invalid .env entry at line {line_number}")
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
    return Settings(mode=mode, home=Path(raw_home).expanduser().resolve())
