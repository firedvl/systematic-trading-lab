"""Pure fail-closed reconciliation of normalized portfolio state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from .fingerprints import fingerprint

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")


class SnapshotSource(StrEnum):
    LOCAL_EXPECTED = "local-expected"
    ALPACA_PAPER = "alpaca-paper"


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: int

    def __post_init__(self) -> None:
        if _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("position symbol must be an uppercase security identifier")
        if isinstance(self.quantity, bool) or self.quantity < 0:
            raise ValueError("position quantity must be a nonnegative whole share count")


@dataclass(frozen=True)
class PortfolioSnapshot:
    snapshot_id: str
    source: SnapshotSource
    account_id: str
    cash: Decimal
    equity: Decimal
    positions: tuple[PositionSnapshot, ...]
    open_client_order_ids: tuple[str, ...]
    account_observed_at: datetime
    positions_observed_at: datetime
    orders_observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source, SnapshotSource):
            raise ValueError("snapshot source is unsupported")
        for text_name, text_value in (
            ("snapshot ID", self.snapshot_id),
            ("account ID", self.account_id),
        ):
            if not text_value or text_value != text_value.strip() or len(text_value) > 128:
                raise ValueError(
                    f"{text_name} must be nonempty, trimmed, and at most 128 characters"
                )
        for amount_name, amount_value in (("cash", self.cash), ("equity", self.equity)):
            if not amount_value.is_finite() or amount_value < 0:
                raise ValueError(f"{amount_name} must be finite and nonnegative")
        if self.positions != tuple(sorted(self.positions, key=lambda item: item.symbol)) or len(
            {position.symbol for position in self.positions}
        ) != len(self.positions):
            raise ValueError("positions must be sorted with unique symbols")
        if self.open_client_order_ids != tuple(sorted(set(self.open_client_order_ids))) or any(
            not value or value != value.strip() or len(value) > 128
            for value in self.open_client_order_ids
        ):
            raise ValueError(
                "open client order IDs must be sorted, unique, nonempty, and at most 128 characters"
            )
        for time_name, time_value in (
            ("account observation", self.account_observed_at),
            ("position observation", self.positions_observed_at),
            ("order observation", self.orders_observed_at),
        ):
            if time_value.tzinfo is None or time_value.utcoffset() != UTC.utcoffset(time_value):
                raise ValueError(f"{time_name} must be UTC-aware")

    @property
    def snapshot_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class ReconciliationResult:
    clean: bool
    reasons: tuple[str, ...]
    expected_fingerprint: str
    observed_fingerprint: str
    compared_at: datetime

    def __post_init__(self) -> None:
        if self.clean != (not self.reasons):
            raise ValueError("reconciliation state must match its reasons")

    @property
    def result_fingerprint(self) -> str:
        return fingerprint(self)


def reconcile(
    expected: PortfolioSnapshot,
    observed: PortfolioSnapshot,
    *,
    compared_at: datetime,
    maximum_age_seconds: int,
    unresolved_mutations: int,
) -> ReconciliationResult:
    """Compare complete normalized state without changing either authority."""
    if compared_at.tzinfo is None or compared_at.utcoffset() != UTC.utcoffset(compared_at):
        raise ValueError("comparison timestamp must be UTC-aware")
    if maximum_age_seconds < 1:
        raise ValueError("maximum snapshot age must be positive")
    if unresolved_mutations < 0:
        raise ValueError("unresolved mutation count must be nonnegative")
    reasons: list[str] = []
    if expected.source is not SnapshotSource.LOCAL_EXPECTED:
        reasons.append("expected-source-invalid")
    if observed.source is not SnapshotSource.ALPACA_PAPER:
        reasons.append("observed-source-invalid")
    if expected.account_id != observed.account_id:
        reasons.append("account-mismatch")
    observed_times = (
        observed.account_observed_at,
        observed.positions_observed_at,
        observed.orders_observed_at,
    )
    if any(
        timestamp > compared_at or (compared_at - timestamp).total_seconds() > maximum_age_seconds
        for timestamp in observed_times
    ):
        reasons.append("observed-state-stale-or-future")
    if expected.cash != observed.cash:
        reasons.append("cash-mismatch")
    if expected.equity != observed.equity:
        reasons.append("equity-mismatch")
    if expected.positions != observed.positions:
        reasons.append("position-mismatch")
    if expected.open_client_order_ids != observed.open_client_order_ids:
        reasons.append("open-order-mismatch")
    if unresolved_mutations:
        reasons.append("unresolved-broker-mutation")
    return ReconciliationResult(
        clean=not reasons,
        reasons=tuple(reasons),
        expected_fingerprint=expected.snapshot_fingerprint,
        observed_fingerprint=observed.snapshot_fingerprint,
        compared_at=compared_at,
    )
