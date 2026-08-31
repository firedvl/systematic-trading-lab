"""Offline-only prospective Program 011 raw SIP session transport."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from . import program_007_alpaca as raw_contract
from . import program_010_ohlcv as predecessor

PROGRAM_ID = "multi-hour-sector-etf-research-010"
PROGRAM_ORDINAL = 11
STATUS = "PROPOSED-NOT-AUTHORIZED"
ENDPOINT = predecessor.ENDPOINT
SYMBOLS = predecessor.SYMBOLS
SELECTED_SESSIONS = (
    date(2021, 4, 28),
    date(2025, 1, 6),
    date(2025, 2, 27),
    date(2025, 11, 28),
    date(2025, 12, 15),
)

PAGE_ROW_LIMIT = predecessor.PAGE_ROW_LIMIT
MAXIMUM_PAGES_PER_SESSION = predecessor.MAXIMUM_PAGES_PER_SESSION
MAXIMUM_RESPONSE_PAGE_BYTES = predecessor.MAXIMUM_RESPONSE_PAGE_BYTES
MAXIMUM_SESSION_RESPONSE_BYTES = predecessor.MAXIMUM_SESSION_RESPONSE_BYTES
MAXIMUM_QUALIFICATION_RESPONSE_BYTES = predecessor.MAXIMUM_QUALIFICATION_RESPONSE_BYTES
MAXIMUM_QUALIFICATION_REQUESTS = len(SELECTED_SESSIONS) * MAXIMUM_PAGES_PER_SESSION
AUTOMATIC_RETRIES = 0

Coordinate = predecessor.Coordinate
PageIntent = predecessor.PageIntent
RetainedPage = predecessor.RetainedPage
PageEvidence = predecessor.PageEvidence


class Program011Error(ValueError):
    """Fail-closed prospective transport error."""


@dataclass(frozen=True)
class Missingness:
    source_missing: tuple[Coordinate, ...]
    unobserved: tuple[Coordinate, ...]


class ChainIncompleteError(Program011Error):
    """A nonterminal chain reached the operational resource cap."""

    def __init__(self, page_count: int, observed_count: int, missingness: Missingness) -> None:
        super().__init__(
            "Program 011 chain is incomplete at the resource safety cap; "
            "remaining coordinates are not source missing"
        )
        self.classification = "CHAIN-INCOMPLETE-RESOURCE-CAP"
        self.page_count = page_count
        self.observed_count = observed_count
        self.missingness = missingness


class CatastrophicCoverageError(Program011Error):
    """A terminal session lacks meaningful per-symbol canonical coverage."""

    def __init__(
        self, insufficient_symbols: tuple[str, ...], minimum_coordinates_per_symbol: int
    ) -> None:
        super().__init__(
            "Program 011 catastrophic canonical coverage failure: "
            f"{','.join(insufficient_symbols)} below {minimum_coordinates_per_symbol} coordinates"
        )
        self.insufficient_symbols = insufficient_symbols
        self.minimum_coordinates_per_symbol = minimum_coordinates_per_symbol


@dataclass(frozen=True)
class SessionRequest(predecessor.SessionRequest):
    def __post_init__(self) -> None:
        if type(self.session) is not date or not self.grid:
            raise Program011Error("Program 011 request session is not an XNYS session")

    def url(self, page_token: str | None = None) -> str:
        try:
            return super().url(page_token)
        except predecessor.Program010Error as error:
            raise Program011Error(str(error).replace("Program 010", "Program 011")) from None

    def parse_page(self, body: bytes) -> tuple[tuple[raw_contract.RawBar, ...], str | None]:
        try:
            received_rows, outgoing_token = raw_contract.parse_raw_page(
                body, self.parser_chain, preserve_received_order=True
            )
        except raw_contract.Program007Error as error:
            raise Program011Error(str(error).replace("Program 007", "Program 011")) from None
        latest_by_symbol: dict[str, datetime] = {}
        for row in received_rows:
            previous = latest_by_symbol.get(row.symbol)
            if previous is not None and row.timestamp <= previous:
                raise Program011Error(
                    "Program 011 response timestamps are not ascending within a symbol array"
                )
            latest_by_symbol[row.symbol] = row.timestamp
        return tuple(sorted(received_rows)), outgoing_token


@dataclass(frozen=True)
class SessionResult:
    request: SessionRequest
    rows: tuple[raw_contract.RawBar, ...]
    pages: tuple[PageEvidence, ...]
    missingness: Missingness

    @property
    def status(self) -> str:
        return "PASS-WITH-SOURCE-MISSING" if self.missingness.source_missing else "PASS"

    @property
    def response_bytes(self) -> int:
        return sum(page.response_bytes for page in self.pages)

    def public_summary(self) -> dict[str, object]:
        return {
            "session": self.request.session.isoformat(),
            "status": self.status,
            "page_count": len(self.pages),
            "raw_row_count": len(self.rows),
            "expected_canonical_coordinate_count": len(self.request.expected_coordinates),
            "source_missing_coordinate_count": len(self.missingness.source_missing),
            "source_missing_coordinates": [
                f"{symbol}@{predecessor._iso_utc(timestamp)}"
                for symbol, timestamp in self.missingness.source_missing
            ],
            "unobserved_coordinate_count": 0,
            "terminal_page_token": None,
        }


@dataclass(frozen=True)
class QualificationResult:
    sessions: tuple[SessionResult, ...]

    @property
    def status(self) -> str:
        return (
            "PASS-WITH-SOURCE-MISSING"
            if any(result.missingness.source_missing for result in self.sessions)
            else "PASS"
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "program_id": PROGRAM_ID,
            "status": self.status,
            "session_count": len(self.sessions),
            "page_count": sum(len(result.pages) for result in self.sessions),
            "response_bytes": sum(result.response_bytes for result in self.sessions),
            "expected_canonical_coordinate_count": sum(
                len(result.request.expected_coordinates) for result in self.sessions
            ),
            "source_missing_coordinate_count": sum(
                len(result.missingness.source_missing) for result in self.sessions
            ),
            "sessions": [result.public_summary() for result in self.sessions],
        }


class SyntheticSessionSource(predecessor.SyntheticSessionSource):
    """Program 011 wrapper around the predecessor's finite raw evidence source."""

    def response(self, intent: PageIntent) -> raw_contract.RawResponse:
        try:
            return super().response(intent)
        except predecessor.Program010Error as error:
            raise Program011Error(str(error).replace("Program 010", "Program 011")) from None

    def retain(self, page_index: int, body: bytes) -> RetainedPage:
        try:
            return super().retain(page_index, body)
        except predecessor.Program010Error as error:
            raise Program011Error(str(error).replace("Program 010", "Program 011")) from None


def qualification_requests() -> tuple[SessionRequest, ...]:
    return tuple(SessionRequest(session) for session in SELECTED_SESSIONS)


def classify_missingness(
    expected: Iterable[Coordinate],
    observed: Iterable[Coordinate],
    *,
    terminal: bool,
    frontier: Coordinate | None = None,
) -> Missingness:
    try:
        result = predecessor.classify_missingness(
            expected, observed, terminal=terminal, frontier=frontier
        )
    except predecessor.Program010Error as error:
        raise Program011Error(str(error).replace("Program 010", "Program 011")) from None
    return Missingness(result.source_missing, result.unobserved)


def execute_synthetic_session(
    request: SessionRequest, source: SyntheticSessionSource
) -> SessionResult:
    if type(source) is not SyntheticSessionSource:
        raise Program011Error("Program 011 accepts exact synthetic session inputs only")
    try:
        if type(request) is not SessionRequest:
            raise Program011Error("Program 011 accepts exact synthetic session inputs only")
        return _execute_synthetic_session(request, source)
    finally:
        source.close()


def _execute_synthetic_session(
    request: SessionRequest, source: SyntheticSessionSource
) -> SessionResult:
    try:
        result = predecessor._execute_synthetic_session(request, source)
    except predecessor.ChainIncompleteError as error:
        missingness = Missingness(error.missingness.source_missing, error.missingness.unobserved)
        raise ChainIncompleteError(error.page_count, error.observed_count, missingness) from None
    except predecessor.CatastrophicCoverageError as error:
        raise CatastrophicCoverageError(
            error.insufficient_symbols, error.minimum_coordinates_per_symbol
        ) from None
    except predecessor.Program010Error as error:
        raise Program011Error(str(error).replace("Program 010", "Program 011")) from None
    return SessionResult(
        request,
        result.rows,
        result.pages,
        Missingness(result.missingness.source_missing, result.missingness.unobserved),
    )


def execute_synthetic_qualification(source: SyntheticSessionSource) -> QualificationResult:
    if type(source) is not SyntheticSessionSource:
        raise Program011Error("Program 011 accepts an exact synthetic source only")
    try:
        results: list[SessionResult] = []
        for request in qualification_requests():
            results.append(_execute_synthetic_session(request, source))
            if len(source.intents) > MAXIMUM_QUALIFICATION_REQUESTS:
                raise Program011Error("Program 011 qualification request ceiling exceeded")
            if sum(page.byte_count for page in source.retained_pages) > (
                MAXIMUM_QUALIFICATION_RESPONSE_BYTES
            ):
                raise Program011Error("Program 011 qualification byte ceiling exceeded")
        return QualificationResult(tuple(results))
    finally:
        source.close()
