"""Fail-closed runtime configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .domain import TradingMode


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    mode: TradingMode
    home: Path

    @property
    def broker_writes_allowed(self) -> bool:
        return False


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
