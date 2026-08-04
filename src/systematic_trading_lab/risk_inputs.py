"""Production-attested read-only quote and market-clock evidence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .reconciliation import (
    PortfolioSnapshot,
    ReconciliationStore,
    _decode_attestation,
    _decode_snapshot,
)
from .risk import RiskLimits, _decode_authorization

DATA_ORIGIN = "https://data.alpaca.markets"
PAPER_ORIGIN = "https://paper-api.alpaca.markets"
_ADAPTER_VERSION = "alpaca-risk-input-reader-v1"
_PRICING_BASIS = "iex-ask-long-exposure-v1"
_CAPABILITY = object()
_Transport = Callable[[Request], bytes]
_Clock = Callable[[], datetime]


class AlpacaRiskInputError(RuntimeError):
    pass


@dataclass(frozen=True)
class LatestQuoteEvidence:
    symbol: str
    bid_price: Decimal
    ask_price: Decimal
    bid_size: int
    ask_size: int
    provider_timestamp: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.upper() or len(self.symbol) > 16:
            raise ValueError("quote symbol is invalid")
        if (
            not self.bid_price.is_finite()
            or not self.ask_price.is_finite()
            or self.bid_price <= 0
            or self.ask_price < self.bid_price
        ):
            raise ValueError("quote prices are invalid")
        if self.bid_size < 1 or self.ask_size < 1:
            raise ValueError("quote sizes must be positive")
        _utc("quote provider timestamp", self.provider_timestamp)
        _utc("quote observation", self.observed_at)
        if self.provider_timestamp > self.observed_at:
            raise ValueError("quote cannot be observed before its provider timestamp")


@dataclass(frozen=True)
class MarketClockEvidence:
    market: str
    phase: str
    is_market_day: bool
    provider_timestamp: datetime
    next_market_open: datetime
    next_market_close: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.market != "NYSE" or self.phase not in {"closed", "pre", "core", "lunch", "post"}:
            raise ValueError("market clock state is unsupported")
        if not isinstance(self.is_market_day, bool):
            raise ValueError("market-day state must be boolean")
        for name, value in (
            ("clock provider timestamp", self.provider_timestamp),
            ("next market open", self.next_market_open),
            ("next market close", self.next_market_close),
            ("clock observation", self.observed_at),
        ):
            _utc(name, value)
        if self.provider_timestamp > self.observed_at:
            raise ValueError("clock cannot be observed before its provider timestamp")
        if (
            self.next_market_open <= self.provider_timestamp
            or self.next_market_close <= self.provider_timestamp
            or (self.phase == "core" and not self.is_market_day)
            or (self.phase == "core" and self.next_market_close >= self.next_market_open)
            or (self.phase != "core" and self.next_market_open >= self.next_market_close)
        ):
            raise ValueError("market clock times are inconsistent")

    @property
    def regular_session_open(self) -> bool:
        return self.phase == "core"


@dataclass(frozen=True)
class RiskInputEvidence:
    portfolio_snapshot_id: str
    portfolio_snapshot_fingerprint: str
    portfolio_attestation_fingerprint: str
    authorization_id: str
    account_id: str
    risk_configuration_fingerprint: str
    maximum_age_seconds: int
    quotes: tuple[LatestQuoteEvidence, ...]
    clock: MarketClockEvidence
    data_origin: str
    paper_origin: str
    quote_path: str
    clock_path: str
    feed: str
    adapter_version: str
    completed_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("portfolio snapshot ID", self.portfolio_snapshot_id),
            ("authorization ID", self.authorization_id),
            ("account ID", self.account_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        for value in (
            self.portfolio_snapshot_fingerprint,
            self.portfolio_attestation_fingerprint,
            self.risk_configuration_fingerprint,
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("risk-input fingerprint is invalid")
        if (
            not self.quotes
            or self.quotes != tuple(sorted(self.quotes, key=lambda item: item.symbol))
            or len({item.symbol for item in self.quotes}) != len(self.quotes)
        ):
            raise ValueError("risk-input quotes must be sorted and unique")
        if isinstance(self.maximum_age_seconds, bool) or self.maximum_age_seconds < 1:
            raise ValueError("risk-input maximum age must be positive")
        if (
            self.data_origin != DATA_ORIGIN
            or self.paper_origin != PAPER_ORIGIN
            or self.quote_path != "/v2/stocks/quotes/latest"
            or self.clock_path != "/v3/clock"
            or self.feed != "iex"
            or self.adapter_version != _ADAPTER_VERSION
        ):
            raise ValueError("risk-input adapter provenance is unsupported")
        _utc("risk-input completion", self.completed_at)
        if self.completed_at != max(
            self.clock.observed_at, *(quote.observed_at for quote in self.quotes)
        ):
            raise ValueError("risk-input completion must match its final observation")
        if (
            any(
                (quote.observed_at - quote.provider_timestamp).total_seconds()
                > self.maximum_age_seconds
                for quote in self.quotes
            )
            or (self.clock.observed_at - self.clock.provider_timestamp).total_seconds()
            > self.maximum_age_seconds
        ):
            raise ValueError("risk-input market evidence is stale")

    @property
    def evidence_id(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class LongExposureValuation:
    risk_input_evidence_id: str
    portfolio_snapshot_id: str
    symbol: str
    current_quantity: int
    exposure_price: Decimal
    current_symbol_notional: Decimal
    current_gross_exposure: Decimal
    pricing_basis: str

    def __post_init__(self) -> None:
        if len(self.risk_input_evidence_id) != 64 or any(
            character not in "0123456789abcdef" for character in self.risk_input_evidence_id
        ):
            raise ValueError("valuation fingerprint is invalid")
        if (
            not self.portfolio_snapshot_id
            or self.portfolio_snapshot_id != self.portfolio_snapshot_id.strip()
            or not self.symbol
            or self.symbol != self.symbol.upper()
        ):
            raise ValueError("valuation authority is invalid")
        if isinstance(self.current_quantity, bool) or self.current_quantity < 0:
            raise ValueError("valuation quantity cannot be negative")
        for amount in (
            self.exposure_price,
            self.current_symbol_notional,
            self.current_gross_exposure,
        ):
            if not amount.is_finite() or amount < 0:
                raise ValueError("valuation amount is invalid")
        if (
            self.exposure_price <= 0
            or self.current_symbol_notional != self.exposure_price * self.current_quantity
            or self.current_symbol_notional > self.current_gross_exposure
        ):
            raise ValueError("valuation totals are inconsistent")
        if self.pricing_basis != _PRICING_BASIS:
            raise ValueError("valuation pricing basis is unsupported")

    @property
    def valuation_fingerprint(self) -> str:
        return fingerprint(self)


def derive_long_exposure(
    evidence: RiskInputEvidence, snapshot: PortfolioSnapshot, *, symbol: str
) -> LongExposureValuation:
    """Value long-only exposure at IEX asks for conservative risk admission."""
    if (
        snapshot.snapshot_id != evidence.portfolio_snapshot_id
        or snapshot.snapshot_fingerprint != evidence.portfolio_snapshot_fingerprint
        or snapshot.account_id != evidence.account_id
    ):
        raise ValueError("valuation snapshot differs from risk-input evidence")
    quotes = {quote.symbol: quote.ask_price for quote in evidence.quotes}
    positions = {position.symbol: position.quantity for position in snapshot.positions}
    if symbol not in quotes or not set(positions).issubset(quotes):
        raise ValueError("valuation requires a quote for every position and target symbol")
    exposure_price = quotes[symbol]
    quantity = positions.get(symbol, 0)
    return LongExposureValuation(
        risk_input_evidence_id=evidence.evidence_id,
        portfolio_snapshot_id=snapshot.snapshot_id,
        symbol=symbol,
        current_quantity=quantity,
        exposure_price=exposure_price,
        current_symbol_notional=exposure_price * quantity,
        current_gross_exposure=sum(
            (
                quotes[position_symbol] * position_quantity
                for position_symbol, position_quantity in positions.items()
            ),
            Decimal(0),
        ),
        pricing_basis=_PRICING_BASIS,
    )


class RiskInputEvidenceStore(ReconciliationStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS risk_input_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    portfolio_snapshot_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id),
                    authorization_id TEXT NOT NULL
                        REFERENCES paper_authorizations(authorization_id),
                    evidence_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS risk_input_evidence_no_update
                BEFORE UPDATE ON risk_input_evidence BEGIN
                    SELECT RAISE(ABORT, 'risk input evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS risk_input_evidence_no_delete
                BEFORE DELETE ON risk_input_evidence BEGIN
                    SELECT RAISE(ABORT, 'risk input evidence is immutable');
                END;
                """
            )
            connection.commit()
            self._verify_risk_inputs(connection)

    def _record(
        self, evidence: RiskInputEvidence, *, recorded_at: datetime, capability: object
    ) -> RiskInputEvidence:
        if capability is not _CAPABILITY:
            raise PermissionError("only the production risk-input reader can attest evidence")
        _utc("risk-input record time", recorded_at)
        if recorded_at < evidence.completed_at:
            raise ValueError("risk-input record time cannot predate completion")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            inputs = self._verify_risk_inputs(connection)
            snapshots, attestations, _, _ = self._verify_reconciliation(connection)
            authorizations = self._verify_authorizations(connection)
            try:
                snapshot = snapshots[evidence.portfolio_snapshot_id]
                attestation = attestations[evidence.portfolio_snapshot_id]
                authorization = authorizations[evidence.authorization_id]
            except KeyError as error:
                raise JournalIntegrityError(
                    "risk inputs require an attested portfolio and authorization"
                ) from error
            _validate_snapshot_boundary(snapshot, evidence)
            if (
                snapshot.snapshot_fingerprint != evidence.portfolio_snapshot_fingerprint
                or snapshot.account_id != evidence.account_id
                or attestation.attestation_fingerprint != evidence.portfolio_attestation_fingerprint
                or authorization.account_id != evidence.account_id
                or authorization.risk_configuration_fingerprint
                != evidence.risk_configuration_fingerprint
                or evidence.completed_at < authorization.authorized_at
                or recorded_at >= authorization.expires_at
            ):
                raise JournalIntegrityError("risk inputs differ from their portfolio authority")
            existing = inputs.get(evidence.evidence_id)
            if existing is not None:
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=recorded_at,
                event_type="risk-input-attested",
                entity_type="risk-input-evidence",
                entity_id=evidence.evidence_id,
                payload=canonicalize(evidence),
            )
            connection.execute(
                "INSERT INTO risk_input_evidence VALUES (?, ?, ?, ?, ?)",
                (
                    evidence.evidence_id,
                    evidence.portfolio_snapshot_id,
                    evidence.authorization_id,
                    canonical_json(evidence),
                    sequence,
                ),
            )
            connection.commit()
        return evidence

    def _verify_risk_inputs(self, connection: sqlite3.Connection) -> dict[str, RiskInputEvidence]:
        rows = connection.execute(
            "SELECT evidence_id, portfolio_snapshot_id, authorization_id, evidence_json, "
            "journal_sequence "
            "FROM risk_input_evidence"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'risk-input-attested'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("risk input and journal counts differ")
        result: dict[str, RiskInputEvidence] = {}
        for row in rows:
            try:
                evidence = _decode_evidence(json.loads(row[3]))
                snapshot_row = connection.execute(
                    "SELECT snapshot_json FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (evidence.portfolio_snapshot_id,),
                ).fetchone()
                attestation_row = connection.execute(
                    "SELECT attestation_json FROM paper_snapshot_attestations "
                    "WHERE snapshot_id = ?",
                    (evidence.portfolio_snapshot_id,),
                ).fetchone()
                authorization_row = connection.execute(
                    "SELECT authorization_json FROM paper_authorizations "
                    "WHERE authorization_id = ?",
                    (evidence.authorization_id,),
                ).fetchone()
                if snapshot_row is None or attestation_row is None or authorization_row is None:
                    raise ValueError("risk input authority is missing")
                snapshot = _decode_snapshot(json.loads(snapshot_row[0]))
                attestation = _decode_attestation(json.loads(attestation_row[0]))
                authorization = _decode_authorization(json.loads(authorization_row[0]))
                _validate_snapshot_boundary(snapshot, evidence)
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored risk input is invalid") from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[4],),
            ).fetchone()
            if (
                row[:3]
                != (
                    evidence.evidence_id,
                    evidence.portfolio_snapshot_id,
                    evidence.authorization_id,
                )
                or row[3] != canonical_json(evidence)
                or snapshot.snapshot_fingerprint != evidence.portfolio_snapshot_fingerprint
                or snapshot.account_id != evidence.account_id
                or attestation.snapshot != snapshot
                or attestation.attestation_fingerprint != evidence.portfolio_attestation_fingerprint
                or authorization.account_id != evidence.account_id
                or authorization.risk_configuration_fingerprint
                != evidence.risk_configuration_fingerprint
                or evidence.completed_at < authorization.authorized_at
                or journal is None
                or journal[1:]
                != (
                    "risk-input-attested",
                    "risk-input-evidence",
                    evidence.evidence_id,
                    canonical_json(evidence),
                )
                or _parse_utc(str(journal[0])) < evidence.completed_at
                or _parse_utc(str(journal[0])) >= authorization.expires_at
            ):
                raise JournalIntegrityError("risk input does not match its journal")
            result[evidence.evidence_id] = evidence
        return result


class AlpacaRiskInputReader:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        limits: RiskLimits,
        transport: _Transport | None = None,
        clock: _Clock | None = None,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca API credentials are required")
        self._api_key = api_key
        self._secret_key = secret_key
        self._limits = limits
        self._allows_persistence = transport is None
        self._transport = transport or _urlopen_bytes
        self._clock = clock or (lambda: datetime.now(UTC))

    def record(
        self,
        store: RiskInputEvidenceStore,
        *,
        portfolio_snapshot_id: str,
        authorization_id: str,
        recorded_at: datetime,
    ) -> RiskInputEvidence:
        if not self._allows_persistence:
            raise AlpacaRiskInputError("injected transport cannot produce durable provenance")
        _utc("risk-input record time", recorded_at)
        if recorded_at < self._limits.effective_at or recorded_at >= self._limits.expires_at:
            raise AlpacaRiskInputError("risk configuration is not active")
        with store._connect() as connection:
            connection.execute("BEGIN")
            snapshots, attestations, _, _ = store._verify_reconciliation(connection)
            authorizations = store._verify_authorizations(connection)
        try:
            snapshot = snapshots[portfolio_snapshot_id]
            attestation = attestations[portfolio_snapshot_id]
            authorization = authorizations[authorization_id]
        except KeyError as error:
            raise JournalIntegrityError(
                "risk inputs require an attested portfolio and authorization"
            ) from error
        if (
            snapshot.account_id != self._limits.account_id
            or authorization.account_id != self._limits.account_id
            or authorization.risk_configuration_fingerprint
            != self._limits.configuration_fingerprint
            or recorded_at < authorization.authorized_at
            or recorded_at >= authorization.expires_at
        ):
            raise AlpacaRiskInputError("risk-input authority differs from active limits")
        quotes = self._read_quotes(self._limits.max_snapshot_age_seconds)
        market_clock = self._read_clock(self._limits.max_snapshot_age_seconds)
        evidence = RiskInputEvidence(
            portfolio_snapshot_id=portfolio_snapshot_id,
            portfolio_snapshot_fingerprint=snapshot.snapshot_fingerprint,
            portfolio_attestation_fingerprint=attestation.attestation_fingerprint,
            authorization_id=authorization_id,
            account_id=self._limits.account_id,
            risk_configuration_fingerprint=self._limits.configuration_fingerprint,
            maximum_age_seconds=self._limits.max_snapshot_age_seconds,
            quotes=quotes,
            clock=market_clock,
            data_origin=DATA_ORIGIN,
            paper_origin=PAPER_ORIGIN,
            quote_path="/v2/stocks/quotes/latest",
            clock_path="/v3/clock",
            feed="iex",
            adapter_version=_ADAPTER_VERSION,
            completed_at=max(market_clock.observed_at, *(item.observed_at for item in quotes)),
        )
        return store._record(evidence, recorded_at=recorded_at, capability=_CAPABILITY)

    def _read_quotes(self, maximum_age_seconds: int) -> tuple[LatestQuoteEvidence, ...]:
        payload = self._get(
            f"{DATA_ORIGIN}/v2/stocks/quotes/latest?"
            f"{urlencode({'symbols': ','.join(self._limits.allowed_symbols), 'feed': 'iex'})}"
        )
        values = payload.get("quotes")
        if not isinstance(values, dict) or set(values) != set(self._limits.allowed_symbols):
            raise AlpacaRiskInputError("latest quote response is incomplete")
        observed_at = self._now()
        quotes = tuple(
            sorted(
                (
                    _quote(symbol, values[symbol], observed_at)
                    for symbol in self._limits.allowed_symbols
                ),
                key=lambda item: item.symbol,
            )
        )
        if any(
            (observed_at - item.provider_timestamp).total_seconds() > maximum_age_seconds
            for item in quotes
        ):
            raise AlpacaRiskInputError("latest quote is stale")
        return quotes

    def _read_clock(self, maximum_age_seconds: int) -> MarketClockEvidence:
        payload = self._get(f"{PAPER_ORIGIN}/v3/clock?markets=NYSE")
        values = payload.get("clocks")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise AlpacaRiskInputError("market clock response is incomplete")
        value = values[0]
        market = value.get("market")
        is_market_day = value.get("is_market_day")
        observed_at = self._now()
        if (
            not isinstance(market, dict)
            or market.get("acronym") != "NYSE"
            or not isinstance(is_market_day, bool)
        ):
            raise AlpacaRiskInputError("market clock is not NYSE")
        result = MarketClockEvidence(
            market="NYSE",
            phase=str(value.get("phase")),
            is_market_day=is_market_day,
            provider_timestamp=_timestamp(value.get("timestamp")),
            next_market_open=_timestamp(value.get("next_market_open")),
            next_market_close=_timestamp(value.get("next_market_close")),
            observed_at=observed_at,
        )
        if (observed_at - result.provider_timestamp).total_seconds() > maximum_age_seconds:
            raise AlpacaRiskInputError("market clock is stale")
        return result

    def _get(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
            },
            method="GET",
        )
        _validate_request(request)
        try:
            value = json.loads(self._transport(request))
        except HTTPError as error:
            raise AlpacaRiskInputError(
                f"Alpaca risk-input request failed with HTTP status {error.code}"
            ) from None
        except (
            HTTPException,
            URLError,
            TimeoutError,
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise AlpacaRiskInputError("Alpaca risk-input request failed") from None
        if not isinstance(value, dict):
            raise AlpacaRiskInputError("Alpaca risk-input response is invalid")
        return value

    def _now(self) -> datetime:
        value = self._clock()
        _utc("risk-input observation", value)
        return value


def _quote(symbol: str, value: object, observed_at: datetime) -> LatestQuoteEvidence:
    if not isinstance(value, dict):
        raise AlpacaRiskInputError("latest quote has an invalid shape")
    try:
        return LatestQuoteEvidence(
            symbol=symbol,
            bid_price=_decimal(value.get("bp")),
            ask_price=_decimal(value.get("ap")),
            bid_size=_positive_int(value.get("bs")),
            ask_size=_positive_int(value.get("as")),
            provider_timestamp=_timestamp(value.get("t")),
            observed_at=observed_at,
        )
    except (TypeError, ValueError) as error:
        raise AlpacaRiskInputError("latest quote is invalid") from error


def _decode_evidence(value: object) -> RiskInputEvidence:
    if not isinstance(value, dict):
        raise ValueError("risk input must be an object")
    try:
        quotes = tuple(
            LatestQuoteEvidence(
                **{
                    **item,
                    "bid_price": Decimal(item["bid_price"]),
                    "ask_price": Decimal(item["ask_price"]),
                    "provider_timestamp": _parse_utc(item["provider_timestamp"]),
                    "observed_at": _parse_utc(item["observed_at"]),
                }
            )
            for item in value["quotes"]
        )
        clock_value = value["clock"]
        clock = MarketClockEvidence(
            **{
                **clock_value,
                "provider_timestamp": _parse_utc(clock_value["provider_timestamp"]),
                "next_market_open": _parse_utc(clock_value["next_market_open"]),
                "next_market_close": _parse_utc(clock_value["next_market_close"]),
                "observed_at": _parse_utc(clock_value["observed_at"]),
            }
        )
        return RiskInputEvidence(
            **{
                **value,
                "quotes": quotes,
                "clock": clock,
                "completed_at": _parse_utc(value["completed_at"]),
            }
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise ValueError("risk input is invalid") from error


def _validate_snapshot_boundary(snapshot: PortfolioSnapshot, evidence: RiskInputEvidence) -> None:
    if any(
        timestamp > evidence.completed_at
        or (evidence.completed_at - timestamp).total_seconds() > evidence.maximum_age_seconds
        for timestamp in (
            snapshot.account_observed_at,
            snapshot.positions_observed_at,
            snapshot.orders_observed_at,
        )
    ):
        raise ValueError("risk input portfolio snapshot is stale or future-dated")


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("amount is invalid") from None
    return result


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("quantity is invalid")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is invalid")
    return _parse_utc(value)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be UTC-aware")


def _validate_request(request: Request) -> None:
    parsed = urlsplit(request.full_url)
    query = parse_qs(parsed.query)
    valid = (
        parsed.netloc == "data.alpaca.markets"
        and parsed.path == "/v2/stocks/quotes/latest"
        and query == {"symbols": [query.get("symbols", [""])[0]], "feed": ["iex"]}
        and bool(query["symbols"][0])
    ) or (
        parsed.netloc == "paper-api.alpaca.markets"
        and parsed.path == "/v3/clock"
        and query == {"markets": ["NYSE"]}
    )
    if request.get_method() != "GET" or parsed.scheme != "https" or parsed.fragment or not valid:
        raise AlpacaRiskInputError("Alpaca risk-input request target is not allowed")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _urlopen_bytes(request: Request) -> bytes:
    _validate_request(request)
    with build_opener(_RejectRedirects).open(request, timeout=30) as response:
        if response.geturl() != request.full_url:
            raise AlpacaRiskInputError("Alpaca risk-input response redirected")
        return cast(bytes, response.read())
