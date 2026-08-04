from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.config import ConfigurationError, load_dotenv, load_settings
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.validation import validate_records


def test_configuration_defaults_offline_and_rejects_live() -> None:
    settings = load_settings({})
    assert settings.mode.value == "offline"
    assert settings.broker_writes_allowed is False
    with pytest.raises(ConfigurationError, match="live trading is disabled"):
        load_settings({"TRADING_LAB_MODE": "live"})
    request_values = {
        "TRADING_LAB_MODE": "paper",
        "TRADING_LAB_PAPER_ACTIVATION_ID": "a" * 64,
        "TRADING_LAB_PAPER_CODE_COMMIT": "reviewed-commit",
    }
    requested = load_settings(request_values)
    assert requested.paper_write_request is not None
    assert requested.paper_write_request.request_fingerprint
    assert requested.broker_writes_allowed is False
    with pytest.raises(ConfigurationError, match="activation ID and code commit"):
        load_settings({"TRADING_LAB_MODE": "paper", "TRADING_LAB_PAPER_ACTIVATION_ID": "a" * 64})
    with pytest.raises(ConfigurationError, match="requires paper mode"):
        load_settings({**request_values, "TRADING_LAB_MODE": "research"})


def test_dotenv_loads_supported_values_without_overriding_environment(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "TRADING_LAB_MODE=research\n"
        "TRADING_LAB_HOME=.trading-lab\n"
        "APCA_API_KEY_ID=file-key\n"
        "APCA_API_SECRET_KEY='file-secret'\n",
        encoding="utf-8",
    )
    environment = {"APCA_API_KEY_ID": "process-key"}

    load_dotenv(path, environment)

    assert environment == {
        "TRADING_LAB_MODE": "research",
        "TRADING_LAB_HOME": ".trading-lab",
        "APCA_API_KEY_ID": "process-key",
        "APCA_API_SECRET_KEY": "file-secret",
    }


def test_dotenv_rejects_unknown_entries(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("UNSUPPORTED_SETTING=value\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid .env entry"):
        load_dotenv(path, {})


def test_canonical_fingerprint_normalizes_decimal_and_mapping_order() -> None:
    left = {"price": Decimal("100.00"), "symbol": "SPY"}
    right = {"symbol": "SPY", "price": Decimal("100")}
    assert fingerprint(left) == fingerprint(right)


def test_bar_rejects_impossible_prices_and_validation_quarantines_duplicate() -> None:
    with pytest.raises(ValueError, match="high"):
        OHLCVBar(
            Symbol("SPY"),
            datetime(2025, 1, 6, tzinfo=UTC),
            Decimal("100"),
            Decimal("99"),
            Decimal("98"),
            Decimal("100"),
            1,
        )
    record: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": "2025-01-06T00:00:00Z",
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100.5",
        "volume": 10,
    }
    result = validate_records([record, record], Timeframe.DAILY)
    assert not result.result.valid
    assert result.result.duplicate_intervals == ("SPY@2025-01-06T00:00:00+00:00",)
    assert result.result.quarantined_records == 1
