"""Offline-only prospective Program 010 raw SIP session transport."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import BinaryIO, Self
from urllib.parse import urlencode

from . import program_007_alpaca as raw_contract
from .calendar import expected_bar_timestamps
from .domain import Timeframe
from .fingerprints import fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-009"
PROGRAM_ORDINAL = 10
STATUS = "PROPOSED-NOT-AUTHORIZED"
ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"
SYMBOLS = raw_contract.SYMBOLS
SELECTED_SESSIONS = (
    date(2021, 5, 25),
    date(2021, 7, 2),
    date(2024, 1, 11),
    date(2025, 11, 28),
    date(2025, 12, 15),
)

PAGE_ROW_LIMIT = 1_000
MAXIMUM_PAGES_PER_SESSION = 16
MAXIMUM_RESPONSE_PAGE_BYTES = 8 * 1024 * 1024
MAXIMUM_SESSION_RESPONSE_BYTES = 8 * 1024 * 1024
MAXIMUM_QUALIFICATION_RESPONSE_BYTES = 40 * 1024 * 1024
MAXIMUM_QUALIFICATION_REQUESTS = len(SELECTED_SESSIONS) * MAXIMUM_PAGES_PER_SESSION
AUTOMATIC_RETRIES = 0

Coordinate = tuple[str, datetime]


class Program010Error(ValueError):
    """Fail-closed prospective transport error."""


@dataclass(frozen=True)
class Missingness:
    source_missing: tuple[Coordinate, ...]
    unobserved: tuple[Coordinate, ...]


class ChainIncompleteError(Program010Error):
    """A nonterminal chain reached the operational resource cap."""

    def __init__(self, page_count: int, observed_count: int, missingness: Missingness) -> None:
        super().__init__(
            "Program 010 chain is incomplete at the resource safety cap; "
            "remaining coordinates are not source missing"
        )
        self.classification = "CHAIN-INCOMPLETE-RESOURCE-CAP"
        self.page_count = page_count
        self.observed_count = observed_count
        self.missingness = missingness


class CatastrophicCoverageError(Program010Error):
    """A terminal session lacks meaningful per-symbol canonical coverage."""

    def __init__(
        self, insufficient_symbols: tuple[str, ...], minimum_coordinates_per_symbol: int
    ) -> None:
        super().__init__(
            "Program 010 catastrophic canonical coverage failure: "
            f"{','.join(insufficient_symbols)} below {minimum_coordinates_per_symbol} coordinates"
        )
        self.insufficient_symbols = insufficient_symbols
        self.minimum_coordinates_per_symbol = minimum_coordinates_per_symbol


@dataclass(frozen=True)
class SessionRequest:
    session: date

    def __post_init__(self) -> None:
        if type(self.session) is not date or not self.grid:
            raise Program010Error("Program 010 request session is not an XNYS session")

    @property
    def grid(self) -> tuple[datetime, ...]:
        start = datetime.combine(self.session, time.min, tzinfo=UTC)
        end = datetime.combine(self.session, time.max, tzinfo=UTC)
        return expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)

    @property
    def start(self) -> datetime:
        return self.grid[0]

    @property
    def end(self) -> datetime:
        return self.grid[-1]

    @property
    def parameters(self) -> tuple[tuple[str, str], ...]:
        return (
            ("symbols", ",".join(SYMBOLS)),
            ("start", _iso_utc(self.start)),
            ("end", _iso_utc(self.end)),
            ("feed", "sip"),
            ("timeframe", "5Min"),
            ("adjustment", "raw"),
            ("sort", "asc"),
            ("limit", str(PAGE_ROW_LIMIT)),
            ("asof", "2026-07-31"),
        )

    @property
    def identity(self) -> str:
        return fingerprint(
            {
                "method": "GET",
                "endpoint": ENDPOINT,
                "parameters": self.parameters,
                "session": self.session.isoformat(),
            }
        )

    def url(self, page_token: str | None = None) -> str:
        parameters = self.parameters
        if page_token is not None:
            if not page_token:
                raise Program010Error("Program 010 page token must be non-empty")
            parameters = (*parameters, ("page_token", page_token))
        return f"{ENDPOINT}?{urlencode(parameters)}"

    @property
    def expected_coordinates(self) -> tuple[Coordinate, ...]:
        return tuple((symbol, timestamp) for symbol in SYMBOLS for timestamp in self.grid)

    @property
    def parser_chain(self) -> raw_contract.RequestChain:
        return raw_contract.RequestChain(
            f"session-{self.session.isoformat()}", self.start, self.end, SYMBOLS, 1
        )

    def parse_page(self, body: bytes) -> tuple[tuple[raw_contract.RawBar, ...], str | None]:
        try:
            page_rows, outgoing_token = raw_contract.parse_raw_page(
                body, self.parser_chain, preserve_received_order=True
            )
        except raw_contract.Program007Error as error:
            raise Program010Error(str(error).replace("Program 007", "Program 010")) from None
        if tuple(page_rows) != tuple(sorted(page_rows)):
            raise Program010Error("Program 010 response rows are not in ascending received order")
        return page_rows, outgoing_token


@dataclass(frozen=True)
class PageIntent:
    request_identity: str
    page_index: int
    url: str
    incoming_page_token: str | None


@dataclass(frozen=True)
class RetainedPage:
    page_index: int
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class PageEvidence:
    page_index: int
    response_bytes: int
    response_sha256: str
    raw_row_count: int
    incoming_page_token_present: bool
    outgoing_page_token_present: bool
    first_coordinate: Coordinate | None
    last_coordinate: Coordinate | None


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
                f"{symbol}@{_iso_utc(timestamp)}"
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


class SyntheticSessionSource:
    """Finite responses plus an unnamed fsynced raw-page evidence file."""

    def __init__(self, responses: Sequence[raw_contract.RawResponse | None]) -> None:
        self._responses = tuple(responses)
        self._response_index = 0
        self._evidence: BinaryIO = tempfile.TemporaryFile()  # noqa: SIM115
        self._intents: list[PageIntent] = []
        self._retained: list[RetainedPage] = []
        self._closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def intents(self) -> tuple[PageIntent, ...]:
        return tuple(self._intents)

    @property
    def retained_pages(self) -> tuple[RetainedPage, ...]:
        return tuple(self._retained)

    @property
    def closed(self) -> bool:
        return self._closed

    def response(self, intent: PageIntent) -> raw_contract.RawResponse:
        if self._closed:
            raise Program010Error("Program 010 synthetic source is closed")
        self._intents.append(intent)
        if self._response_index >= len(self._responses):
            raise Program010Error("Program 010 response outcome is ambiguous; zero retries")
        response = self._responses[self._response_index]
        self._response_index += 1
        if type(response) is not raw_contract.RawResponse:
            raise Program010Error("Program 010 response outcome is ambiguous; zero retries")
        return response

    def retain(self, page_index: int, body: bytes) -> RetainedPage:
        if self._closed:
            raise Program010Error("Program 010 synthetic source is closed")
        record = len(body).to_bytes(8, "big") + body
        if self._evidence.write(record) != len(record):
            raise Program010Error("Program 010 raw response persistence was incomplete")
        self._evidence.flush()
        os.fsync(self._evidence.fileno())
        retained = RetainedPage(page_index, len(body), hashlib.sha256(body).hexdigest())
        self._retained.append(retained)
        return retained

    def close(self) -> None:
        if not self._closed:
            self._evidence.close()
            self._closed = True


def qualification_requests() -> tuple[SessionRequest, ...]:
    return tuple(SessionRequest(session) for session in SELECTED_SESSIONS)


def classify_missingness(
    expected: Iterable[Coordinate],
    observed: Iterable[Coordinate],
    *,
    terminal: bool,
    frontier: Coordinate | None = None,
) -> Missingness:
    expected_set = set(expected)
    observed_set = set(observed)
    if not observed_set <= expected_set:
        raise Program010Error("Program 010 observed coordinates exceed the canonical domain")
    missing = expected_set - observed_set
    if terminal:
        return Missingness(tuple(sorted(missing)), ())
    if frontier is None or frontier not in observed_set:
        raise Program010Error("Program 010 incomplete chain lacks a valid ordered frontier")
    return Missingness(
        tuple(sorted(coordinate for coordinate in missing if coordinate < frontier)),
        tuple(sorted(coordinate for coordinate in missing if coordinate > frontier)),
    )


def execute_synthetic_session(
    request: SessionRequest, source: SyntheticSessionSource
) -> SessionResult:
    if type(source) is not SyntheticSessionSource:
        raise Program010Error("Program 010 accepts exact synthetic session inputs only")
    try:
        if type(request) is not SessionRequest:
            raise Program010Error("Program 010 accepts exact synthetic session inputs only")
        return _execute_synthetic_session(request, source)
    finally:
        source.close()


def _execute_synthetic_session(
    request: SessionRequest, source: SyntheticSessionSource
) -> SessionResult:
    rows: list[raw_contract.RawBar] = []
    pages: list[PageEvidence] = []
    seen_coordinates: set[Coordinate] = set()
    seen_hashes: set[str] = set()
    seen_tokens: set[str] = set()
    incoming_token: str | None = None
    frontier: Coordinate | None = None
    response_bytes = 0

    for page_index in range(1, MAXIMUM_PAGES_PER_SESSION + 1):
        intent = PageIntent(
            request.identity, page_index, request.url(incoming_token), incoming_token
        )
        response = source.response(intent)
        if len(response.body) > MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program010Error("Program 010 response exceeds the 8 MiB page ceiling")
        response_bytes += len(response.body)
        if response_bytes > MAXIMUM_SESSION_RESPONSE_BYTES:
            raise Program010Error("Program 010 session exceeds the 8 MiB byte ceiling")
        retained = source.retain(page_index, response.body)
        if response.status != 200:
            raise Program010Error("Program 010 response status is not 200")

        page_rows, outgoing_token = request.parse_page(response.body)
        if len(page_rows) > PAGE_ROW_LIMIT:
            raise Program010Error("Program 010 response exceeds the 1,000-row page limit")
        if retained.sha256 in seen_hashes:
            raise Program010Error("Program 010 response page is repeated")

        page_coordinates = {row.coordinate for row in page_rows}
        if page_coordinates & seen_coordinates:
            raise Program010Error("Program 010 coordinate repeats across pages")
        if page_rows and frontier is not None and page_rows[0].coordinate <= frontier:
            raise Program010Error("Program 010 page ordering does not progress")
        if outgoing_token is not None:
            if outgoing_token == incoming_token or outgoing_token in seen_tokens:
                raise Program010Error("Program 010 pagination token is repeated")
            if not page_rows:
                raise Program010Error("Program 010 nonterminal page makes zero progress")

        seen_hashes.add(retained.sha256)
        seen_coordinates.update(page_coordinates)
        rows.extend(page_rows)
        if page_rows:
            frontier = page_rows[-1].coordinate
        pages.append(
            PageEvidence(
                page_index,
                retained.byte_count,
                retained.sha256,
                len(page_rows),
                incoming_token is not None,
                outgoing_token is not None,
                page_rows[0].coordinate if page_rows else None,
                page_rows[-1].coordinate if page_rows else None,
            )
        )

        if outgoing_token is None:
            missingness = classify_missingness(
                request.expected_coordinates, seen_coordinates, terminal=True
            )
            counts = Counter(symbol for symbol, _ in seen_coordinates)
            minimum_coordinates = len(request.grid) // 2 + 1
            insufficient_symbols = tuple(
                symbol for symbol in SYMBOLS if counts[symbol] < minimum_coordinates
            )
            if insufficient_symbols:
                raise CatastrophicCoverageError(insufficient_symbols, minimum_coordinates)
            return SessionResult(request, tuple(rows), tuple(pages), missingness)

        seen_tokens.add(outgoing_token)
        if page_index == MAXIMUM_PAGES_PER_SESSION:
            missingness = classify_missingness(
                request.expected_coordinates,
                seen_coordinates,
                terminal=False,
                frontier=frontier,
            )
            raise ChainIncompleteError(page_index, len(seen_coordinates), missingness)
        incoming_token = outgoing_token

    raise AssertionError("unreachable Program 010 pagination state")


def execute_synthetic_qualification(source: SyntheticSessionSource) -> QualificationResult:
    if type(source) is not SyntheticSessionSource:
        raise Program010Error("Program 010 accepts an exact synthetic source only")
    try:
        results: list[SessionResult] = []
        for request in qualification_requests():
            results.append(_execute_synthetic_session(request, source))
            if len(source.intents) > MAXIMUM_QUALIFICATION_REQUESTS:
                raise Program010Error("Program 010 qualification request ceiling exceeded")
            if sum(page.byte_count for page in source.retained_pages) > (
                MAXIMUM_QUALIFICATION_RESPONSE_BYTES
            ):
                raise Program010Error("Program 010 qualification byte ceiling exceeded")
        return QualificationResult(tuple(results))
    finally:
        source.close()


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
