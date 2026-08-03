from datetime import UTC, datetime
from decimal import Decimal

import pytest

from systematic_trading_lab.config import ConfigurationError, load_settings
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.validation import validate_records


def test_configuration_defaults_offline_and_rejects_live() -> None:
    settings = load_settings({})
    assert settings.mode.value == "offline"
    assert settings.broker_writes_allowed is False
    with pytest.raises(ConfigurationError, match="live trading is disabled"):
        load_settings({"TRADING_LAB_MODE": "live"})


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
