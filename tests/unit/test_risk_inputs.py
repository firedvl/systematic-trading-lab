from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.reconciliation import (
    PortfolioSnapshot,
    PositionSnapshot,
    SnapshotSource,
)
from systematic_trading_lab.risk_inputs import (
    DATA_ORIGIN,
    PAPER_ORIGIN,
    LatestQuoteEvidence,
    MarketClockEvidence,
    RiskInputEvidence,
    _validate_snapshot_boundary,
    derive_long_exposure,
)

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def test_quote_evidence_rejects_crossed_or_future_quotes() -> None:
    quote = LatestQuoteEvidence(
        symbol="SPY",
        bid_price=Decimal("100"),
        ask_price=Decimal("100.10"),
        bid_size=10,
        ask_size=12,
        provider_timestamp=NOW,
        observed_at=NOW,
    )
    with pytest.raises(ValueError, match="prices"):
        replace(quote, ask_price=Decimal("99"))
    with pytest.raises(ValueError, match="before"):
        replace(quote, provider_timestamp=NOW + timedelta(seconds=1))


def test_clock_evidence_requires_consistent_nyse_core_session() -> None:
    clock = MarketClockEvidence(
        market="NYSE",
        phase="core",
        is_market_day=True,
        provider_timestamp=NOW,
        next_market_open=NOW + timedelta(days=1),
        next_market_close=NOW + timedelta(hours=1),
        observed_at=NOW,
    )
    assert clock.regular_session_open
    with pytest.raises(ValueError, match="inconsistent"):
        replace(clock, is_market_day=False)
    with pytest.raises(ValueError, match="inconsistent"):
        replace(
            clock,
            phase="closed",
            is_market_day=False,
            next_market_open=NOW + timedelta(hours=2),
            next_market_close=NOW + timedelta(hours=1),
        )


def test_risk_inputs_reject_stale_or_future_portfolio_snapshots() -> None:
    quote = LatestQuoteEvidence("SPY", Decimal("100"), Decimal("100.10"), 10, 12, NOW, NOW)
    clock = MarketClockEvidence(
        "NYSE",
        "core",
        True,
        NOW,
        NOW + timedelta(days=1),
        NOW + timedelta(hours=1),
        NOW,
    )
    evidence = RiskInputEvidence(
        portfolio_snapshot_id="snapshot-1",
        portfolio_snapshot_fingerprint=fingerprint({"snapshot": 1}),
        portfolio_attestation_fingerprint=fingerprint({"attestation": 1}),
        authorization_id="authorization-1",
        account_id="paper-account",
        risk_configuration_fingerprint=fingerprint({"limits": 1}),
        maximum_age_seconds=30,
        quotes=(quote,),
        clock=clock,
        data_origin=DATA_ORIGIN,
        paper_origin=PAPER_ORIGIN,
        quote_path="/v2/stocks/quotes/latest",
        clock_path="/v3/clock",
        feed="iex",
        adapter_version="alpaca-risk-input-reader-v1",
        completed_at=NOW,
    )
    snapshot = PortfolioSnapshot(
        "snapshot-1",
        SnapshotSource.ALPACA_PAPER,
        "paper-account",
        Decimal("1"),
        Decimal("1"),
        Decimal("1"),
        True,
        (),
        (),
        NOW,
        NOW,
        NOW,
    )
    _validate_snapshot_boundary(snapshot, evidence)
    with pytest.raises(ValueError, match="stale or future"):
        _validate_snapshot_boundary(
            replace(snapshot, account_observed_at=NOW - timedelta(seconds=31)), evidence
        )
    with pytest.raises(ValueError, match="stale or future"):
        _validate_snapshot_boundary(
            replace(snapshot, orders_observed_at=NOW + timedelta(seconds=1)), evidence
        )

    positioned = replace(snapshot, positions=(PositionSnapshot("SPY", 3),))
    bound_evidence = replace(
        evidence, portfolio_snapshot_fingerprint=positioned.snapshot_fingerprint
    )
    valuation = derive_long_exposure(bound_evidence, positioned, symbol="SPY")
    assert valuation.current_quantity == 3
    assert valuation.exposure_price == Decimal("100.10")
    assert valuation.current_symbol_notional == Decimal("300.30")
    assert valuation.current_gross_exposure == Decimal("300.30")
    unquoted = replace(snapshot, positions=(PositionSnapshot("QQQ", 1),))
    with pytest.raises(ValueError, match="quote for every"):
        derive_long_exposure(
            replace(
                bound_evidence,
                portfolio_snapshot_fingerprint=unquoted.snapshot_fingerprint,
            ),
            unquoted,
            symbol="SPY",
        )
