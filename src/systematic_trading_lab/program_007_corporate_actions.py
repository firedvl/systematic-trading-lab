"""Program 007 corporate-action metadata contract."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from _thread import RLock
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from http.client import HTTPException
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .fingerprints import canonical_json, fingerprint
from .program_007_alpaca import validate_action_ledger

PROGRAM_ID = "multi-hour-sector-etf-research-006"
STATUS = "PROPOSED-NOT-AUTHORIZED"
ENDPOINT = "https://data.alpaca.markets/v1/corporate-actions"
DOCUMENTATION_RETRIEVED = date(2026, 8, 29)
COVERAGE_START = date(2020, 6, 26)
COVERAGE_END = date(2026, 7, 31)
PROCESS_START = date(1990, 1, 1)
PROCESS_END = DOCUMENTATION_RETRIEVED
METADATA_QUERY_END = PROCESS_END
PRIVATE_ROOT = Path(".trading-lab/program-007-corporate-action-metadata-v2")
CREDENTIAL_NAMES = (
    "PROGRAM_007_CORPORATE_ACTIONS_API_KEY_ID",
    "PROGRAM_007_CORPORATE_ACTIONS_API_SECRET_KEY",
)
MAXIMUM_PAGES_PER_CHAIN = 4
MAXIMUM_HTTP_REQUESTS = 8
MAXIMUM_HTTP_RESPONSES = 8
MAXIMUM_RESPONSE_PAGE_BYTES = 1024 * 1024
MAXIMUM_DOWNLOADED_BYTES = 8 * 1024 * 1024
AUTOMATIC_TRANSPORT_RETRIES = 0
IDENTITY_HISTORY_STATUS = "PUBLIC-LEDGER-V3-CONTINUITY-CLOSED"
SOURCE_FINALITY_STATUS = "UNBOUNDED-CREATION-LAG-AS-OF-CORROBORATION-ONLY"

_EVIDENCE_KEY = re.compile(r"[a-z0-9][a-z0-9.-]*")

IDENTITIES = {
    "IWM": "464287655",
    "MDY": "78467Y107",
    "SPY": "78462F103",
    "XLB": "81369Y100",
    "XLE": "81369Y506",
    "XLF": "81369Y605",
    "XLI": "81369Y704",
    "XLK": "81369Y803",
    "XLP": "81369Y308",
    "XLRE": "81369Y860",
    "XLU": "81369Y886",
    "XLV": "81369Y209",
    "XLY": "81369Y407",
}
SYMBOLS = tuple(sorted(IDENTITIES))
CUSIPS = tuple(sorted(IDENTITIES.values()))
POSITIVE_CONTROLS = frozenset({"XLB", "XLE", "XLK", "XLU", "XLY"})
NEGATIVE_CONTROLS = frozenset({"XLF", "XLI", "XLP", "XLRE", "XLV"})

_AUTHORITY = {
    "provider_contact": False,
    "subscription_purchase": False,
    "credential_access": False,
    "source_requests": False,
    "source_qualification": False,
    "market_data_acquisition": False,
    "real_dataset_admission": False,
    "strategy_implementation": False,
    "strategy_execution": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}


class Program007MetadataError(ValueError):
    """Fail-closed Program 007 metadata-contract error."""


class MetadataAccessError(Program007MetadataError):
    """Terminal authentication or entitlement failure."""


@dataclass(frozen=True)
class EventContract:
    array_name: str
    event_type: str
    required: frozenset[str]
    allowed: frozenset[str]
    effective_field: str | None


def _contract(
    array_name: str,
    event_type: str,
    required: str,
    optional: str,
    effective_field: str | None,
) -> EventContract:
    required_fields = frozenset(required.split())
    return EventContract(
        array_name,
        event_type,
        required_fields,
        required_fields | frozenset(optional.split()),
        effective_field,
    )


_CONTRACTS = (
    _contract(
        "forward_splits",
        "forward_split",
        "id symbol cusip new_rate old_rate process_date ex_date",
        "currency isin record_date payable_date due_bill_redemption_date",
        "ex_date",
    ),
    _contract(
        "reverse_splits",
        "reverse_split",
        "id symbol old_cusip new_cusip new_rate old_rate process_date ex_date",
        "currency old_isin new_isin new_symbol record_date payable_date",
        "ex_date",
    ),
    _contract(
        "unit_splits",
        "unit_split",
        "id old_symbol old_cusip old_rate new_symbol new_cusip new_rate "
        "alternate_symbol alternate_cusip alternate_rate process_date effective_date",
        "currency old_isin new_isin alternate_isin payable_date",
        "effective_date",
    ),
    _contract(
        "cash_dividends",
        "cash_dividend",
        "id symbol cusip rate special foreign process_date ex_date",
        "currency isin record_date payable_date due_bill_on_date due_bill_off_date sub_type",
        "ex_date",
    ),
    _contract(
        "stock_dividends",
        "stock_dividend",
        "id symbol cusip rate process_date ex_date",
        "currency isin record_date payable_date",
        "ex_date",
    ),
    _contract(
        "spin_offs",
        "spin_off",
        "id source_symbol source_cusip source_rate new_symbol new_cusip new_rate "
        "process_date ex_date",
        "currency source_isin new_isin record_date payable_date due_bill_redemption_date",
        "ex_date",
    ),
    _contract(
        "cash_mergers",
        "cash_merger",
        "id acquiree_symbol acquiree_cusip rate process_date effective_date",
        "currency acquiree_isin acquirer_symbol acquirer_cusip acquirer_isin payable_date",
        "effective_date",
    ),
    _contract(
        "stock_mergers",
        "stock_merger",
        "id acquirer_symbol acquirer_cusip acquirer_rate acquiree_symbol acquiree_cusip "
        "acquiree_rate process_date effective_date",
        "currency acquirer_isin acquiree_isin payable_date",
        "effective_date",
    ),
    _contract(
        "stock_and_cash_mergers",
        "stock_and_cash_merger",
        "id acquirer_symbol acquirer_cusip acquirer_rate acquiree_symbol acquiree_cusip "
        "acquiree_rate cash_rate process_date effective_date",
        "currency acquirer_isin acquiree_isin payable_date",
        "effective_date",
    ),
    _contract(
        "redemptions",
        "redemption",
        "id symbol cusip rate process_date",
        "currency isin payable_date",
        None,
    ),
    _contract(
        "name_changes",
        "name_change",
        "id old_symbol old_cusip new_symbol new_cusip process_date",
        "currency old_isin new_isin",
        None,
    ),
    _contract(
        "worthless_removals",
        "worthless_removal",
        "id symbol cusip process_date",
        "currency isin",
        None,
    ),
    _contract(
        "rights_distributions",
        "rights_distribution",
        "id source_symbol source_cusip new_symbol new_cusip rate process_date ex_date payable_date",
        "currency source_isin new_isin record_date expiration_date",
        "ex_date",
    ),
    _contract(
        "partial_calls",
        "partial_call",
        "id symbol process_date",
        "currency cusip isin dividend_rate lottery_date lottery_type payable_date price "
        "record_date results_publication_date",
        None,
    ),
    _contract(
        "reorganizations",
        "reorganization",
        "id symbol cusip process_date effective_date",
        "currency isin payable_date cash_rate stock_movements",
        "effective_date",
    ),
    _contract(
        "capital_gains_distributions",
        "capital_gains_distribution",
        "id symbol cusip process_date ex_date",
        "currency isin record_date payable_date long_term_rate short_term_rate",
        "ex_date",
    ),
)
EVENT_TYPES = tuple(contract.event_type for contract in _CONTRACTS)
_CONTRACT_BY_ARRAY = {contract.array_name: contract for contract in _CONTRACTS}
_DATE_FIELDS = frozenset(
    {
        "process_date",
        "ex_date",
        "effective_date",
        "record_date",
        "payable_date",
        "due_bill_redemption_date",
        "due_bill_on_date",
        "due_bill_off_date",
        "expiration_date",
        "lottery_date",
        "results_publication_date",
    }
)
_NUMBER_FIELDS = frozenset(
    {
        "new_rate",
        "old_rate",
        "alternate_rate",
        "rate",
        "source_rate",
        "acquirer_rate",
        "acquiree_rate",
        "cash_rate",
        "dividend_rate",
        "price",
        "long_term_rate",
        "short_term_rate",
    }
)
_NON_UNIT_TYPES = frozenset({"cash_dividend", "capital_gains_distribution"})
_RELEVANT_TYPES = frozenset(EVENT_TYPES) - _NON_UNIT_TYPES


@dataclass(frozen=True)
class RequestChain:
    chain_id: str
    identity_parameter: str
    identities: tuple[str, ...]
    maximum_pages: int = MAXIMUM_PAGES_PER_CHAIN

    def __post_init__(self) -> None:
        expected = SYMBOLS if self.identity_parameter == "symbols" else CUSIPS
        if (
            self.chain_id not in {"symbols", "cusips"}
            or self.identity_parameter not in {"symbols", "cusips"}
            or self.identities != expected
            or self.maximum_pages != MAXIMUM_PAGES_PER_CHAIN
        ):
            raise Program007MetadataError("Program 007 metadata request chain is invalid")

    @property
    def parameters(self) -> tuple[tuple[str, str], ...]:
        return (
            (self.identity_parameter, ",".join(self.identities)),
            ("region", "us"),
            ("start", PROCESS_START.isoformat()),
            ("end", PROCESS_END.isoformat()),
            ("limit", "1000"),
            ("data_quality", "complete"),
            ("sort", "asc"),
        )

    def url(self, page_token: str | None = None) -> str:
        parameters = self.parameters
        if page_token is not None:
            if not page_token:
                raise Program007MetadataError("Program 007 metadata page token is empty")
            parameters = (*parameters, ("page_token", page_token))
        return f"{ENDPOINT}?{urlencode(parameters)}"

    @property
    def identity(self) -> str:
        return fingerprint(
            {
                "method": "GET",
                "endpoint": ENDPOINT,
                "parameters": dict(self.parameters),
                "maximum_pages": self.maximum_pages,
                "redirects": False,
            }
        )


def frozen_request_chains() -> tuple[RequestChain, ...]:
    return (
        RequestChain("symbols", "symbols", SYMBOLS),
        RequestChain("cusips", "cusips", CUSIPS),
    )


@dataclass(frozen=True)
class RequestIntent:
    chain_id: str
    chain_identity: str
    page_index: int
    url: str
    incoming_page_token: str | None
    method: str = "GET"
    redirects: bool = False


@dataclass(frozen=True)
class RawResponse:
    status: int
    body: bytes

    def __post_init__(self) -> None:
        if type(self.status) is not int or type(self.body) is not bytes:
            raise Program007MetadataError("Program 007 metadata response is invalid")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: BinaryIO,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


def _urlopen_response(request: Request) -> RawResponse:
    """Dormant bounded transport for a later, separately authorized integration."""
    _validate_http_request(request)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            return RawResponse(int(response.status), response.read(MAXIMUM_RESPONSE_PAGE_BYTES + 1))
    except HTTPError as error:
        return RawResponse(error.code, error.read(MAXIMUM_RESPONSE_PAGE_BYTES + 1))


class _AlpacaMetadataClient:
    __slots__ = ("_headers", "_transport")

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        transport: Callable[[Request], RawResponse],
    ) -> None:
        if any(not value or "\r" in value or "\n" in value for value in (key_id, secret_key)):
            raise Program007MetadataError("Program 007 metadata credentials are invalid")
        if not callable(transport):
            raise Program007MetadataError("Program 007 metadata transport is invalid")
        self._headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._transport = transport

    def get(self, intent: RequestIntent) -> RawResponse:
        request = Request(intent.url, headers=self._headers, method="GET")
        _validate_http_request(request)
        try:
            response = self._transport(request)
        except (HTTPException, TimeoutError, ConnectionError, URLError, OSError) as error:
            raise Program007MetadataError(
                "Program 007 metadata transport is ambiguous; zero-retry use is consumed"
            ) from error
        if type(response) is not RawResponse:
            raise Program007MetadataError("Program 007 metadata transport response is invalid")
        return response


class MockMetadataTransport:
    """Finite in-memory responses for persistent-boundary tests."""

    __slots__ = ("_requests", "_responses")

    def __init__(self, responses: Sequence[RawResponse]) -> None:
        if type(responses) not in {list, tuple} or any(
            type(response) is not RawResponse for response in responses
        ):
            raise Program007MetadataError("Program 007 mock metadata responses are invalid")
        self._responses = tuple(responses)
        self._requests: list[Request] = []

    @property
    def requests(self) -> tuple[Request, ...]:
        return tuple(self._requests)

    def __call__(self, request: Request) -> RawResponse:
        index = len(self._requests)
        self._requests.append(request)
        if index >= len(self._responses):
            raise Program007MetadataError("Program 007 mock metadata response is missing")
        return self._responses[index]

    def require_exhausted(self) -> None:
        if len(self._requests) != len(self._responses):
            raise Program007MetadataError("Program 007 mock metadata responses remain unused")


class SyntheticMetadataSource:
    """Finite responses retained in a capability-held temporary evidence log."""

    __slots__ = (
        "_responses",
        "_intents",
        "_intent_records_present",
        "_evidence",
        "_evidence_keys",
        "_evidence_lock",
    )

    _responses: tuple[RawResponse | None, ...]
    _intents: list[RequestIntent]
    _intent_records_present: list[bool]
    _evidence: BinaryIO
    _evidence_keys: set[str]
    _evidence_lock: RLock

    def __init__(self, responses: Sequence[RawResponse | None]) -> None:
        if type(responses) not in {list, tuple} or any(
            response is not None and type(response) is not RawResponse for response in responses
        ):
            raise Program007MetadataError("Program 007 synthetic metadata responses are invalid")
        evidence = tempfile.TemporaryFile(  # noqa: SIM115 - held for source lifetime
            mode="w+b", buffering=0, prefix="program-007-metadata-"
        )
        object.__setattr__(self, "_responses", tuple(responses))
        object.__setattr__(self, "_intents", [])
        object.__setattr__(self, "_intent_records_present", [])
        object.__setattr__(self, "_evidence", evidence)
        object.__setattr__(self, "_evidence_keys", set())
        object.__setattr__(self, "_evidence_lock", RLock())

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Program 007 synthetic metadata source is immutable")

    def __enter__(self) -> SyntheticMetadataSource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._evidence.close()

    @property
    def intents(self) -> tuple[RequestIntent, ...]:
        return tuple(self._intents)

    @property
    def intent_records_present(self) -> tuple[bool, ...]:
        return tuple(self._intent_records_present)

    @property
    def evidence_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._evidence_keys))

    @property
    def consumed_response_count(self) -> int:
        return len(self._intents)


@dataclass(frozen=True)
class CanonicalAction:
    provider_event_id: str
    action_type: str
    symbols: tuple[str, ...]
    cusips: tuple[str, ...]
    isins: tuple[str, ...]
    target_symbols: tuple[str, ...]
    subtype: str | None
    process_date: date
    announcement_date: date | None
    effective_date: date | None
    effective_date_field: str | None
    record_date: date | None
    payable_date: date | None
    provider_rates: tuple[tuple[str, str], ...]
    old_units: Fraction | None
    new_units: Fraction | None
    exact_factor: Fraction | None
    classification: str
    source_identity: str

    @property
    def sort_key(self) -> tuple[date, str, str]:
        return self.process_date, self.action_type, self.provider_event_id

    def ledger_record(self) -> Mapping[str, Any]:
        return {
            "provider": "alpaca",
            "provider_event_id": self.provider_event_id,
            "action_type": self.action_type,
            "symbols": list(self.symbols),
            "cusips": list(self.cusips),
            "isins": list(self.isins),
            "target_symbols": list(self.target_symbols),
            "subtype": self.subtype,
            "process_date": self.process_date.isoformat(),
            "announcement_date": None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "effective_date_field": self.effective_date_field,
            "record_date": self.record_date.isoformat() if self.record_date else None,
            "payable_date": self.payable_date.isoformat() if self.payable_date else None,
            "provider_rates": dict(self.provider_rates),
            "old_units": _fraction_record(self.old_units),
            "new_units": _fraction_record(self.new_units),
            "exact_factor": _fraction_record(self.exact_factor),
            "classification": self.classification,
            "source_identity": self.source_identity,
        }


@dataclass(frozen=True)
class PageEvidence:
    chain_id: str
    chain_identity: str
    page_index: int
    request_url: str
    incoming_page_token: str | None
    outgoing_page_token: str | None
    response_sha256: str
    response_bytes: int
    event_count: int


@dataclass(frozen=True)
class ChainResult:
    chain: RequestChain
    events: tuple[CanonicalAction, ...]
    pages: tuple[PageEvidence, ...]


@dataclass(frozen=True)
class MetadataQualificationResult:
    chains: tuple[ChainResult, ...]
    events: tuple[CanonicalAction, ...]

    @property
    def response_count(self) -> int:
        return sum(len(chain.pages) for chain in self.chains)

    @property
    def response_bytes(self) -> int:
        return sum(page.response_bytes for chain in self.chains for page in chain.pages)

    def private_manifest(
        self,
        *,
        status: str = "SYNTHETIC-CONTRACT-PASS",
        metadata_observation_as_of: str | None = None,
        synthetic_credential_loads: int = 0,
    ) -> Mapping[str, Any]:
        return {
            "schema_version": "program-007-private-corporate-action-metadata-manifest-v1",
            "program_id": PROGRAM_ID,
            "status": status,
            "metadata_query_end": METADATA_QUERY_END.isoformat(),
            "metadata_observation_as_of": metadata_observation_as_of,
            "query_chains": [chain.chain.chain_id for chain in self.chains],
            "pages": [
                {
                    "chain_id": page.chain_id,
                    "chain_identity": page.chain_identity,
                    "page_index": page.page_index,
                    "request_url": page.request_url,
                    "incoming_page_token": page.incoming_page_token,
                    "outgoing_page_token": page.outgoing_page_token,
                    "response_sha256": page.response_sha256,
                    "response_bytes": page.response_bytes,
                    "event_count": page.event_count,
                }
                for chain in self.chains
                for page in chain.pages
            ],
            "response_count": self.response_count,
            "response_bytes": self.response_bytes,
            "canonical_event_count": len(self.events),
            "credentials_stored": False,
            "synthetic_credential_loads": synthetic_credential_loads,
            "provider_requests": 0,
            "strategy_outputs": 0,
        }


@dataclass
class _Budget:
    requests: int = 0
    responses: int = 0
    response_bytes: int = 0

    def reserve_request(self) -> None:
        if self.requests >= MAXIMUM_HTTP_REQUESTS:
            raise Program007MetadataError("Program 007 metadata request ceiling exceeded")
        self.requests += 1

    def accept_response(self, body: bytes) -> None:
        if len(body) > MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program007MetadataError("Program 007 metadata page exceeds 1 MiB")
        if self.responses >= MAXIMUM_HTTP_RESPONSES:
            raise Program007MetadataError("Program 007 metadata response ceiling exceeded")
        if self.response_bytes + len(body) > MAXIMUM_DOWNLOADED_BYTES:
            raise Program007MetadataError("Program 007 metadata byte ceiling exceeded")
        self.responses += 1
        self.response_bytes += len(body)


def execute_synthetic_metadata(source: SyntheticMetadataSource) -> MetadataQualificationResult:
    """Run the frozen metadata contract without a network or credential surface."""
    if type(source) is not SyntheticMetadataSource:
        raise Program007MetadataError("Program 007 metadata execution requires a synthetic source")
    if source._evidence.closed:
        raise Program007MetadataError("Program 007 metadata evidence is closed")
    if type(source._evidence_lock) is not RLock:
        raise Program007MetadataError("Program 007 metadata evidence lock is invalid")
    with source._evidence_lock:
        budget = _Budget()
        chains = tuple(
            _execute_chain(
                chain,
                budget,
                lambda intent, intent_key: _next_synthetic_response(source, intent, intent_key),
                lambda key, payload: _append_evidence(source, key, payload),
            )
            for chain in frozen_request_chains()
        )
        _require_synthetic_responses_exhausted(source)
        events = _reconcile_chains(chains)
        result = MetadataQualificationResult(chains, events)
        _append_evidence(
            source,
            "private-manifest.json",
            canonical_json(result.private_manifest()).encode(),
        )
        return result


def execute_mock_persistent_metadata(
    repository: Path,
    *,
    environ: Mapping[str, str],
    transport: MockMetadataTransport,
) -> MetadataQualificationResult:
    """Exercise the future persistent boundary with an explicit mock transport only."""
    if type(transport) is not MockMetadataTransport:
        raise Program007MetadataError("Program 007 persistent execution requires a finite mock")
    private_root = _prepare_private_root(repository)
    lock_descriptor = os.open(
        private_root / "run.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(lock_descriptor, "a+b", buffering=0) as lock:
        if stat.S_IMODE(os.fstat(lock.fileno()).st_mode) & 0o077:
            raise Program007MetadataError("Program 007 evidence lock is not private")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if {path.name for path in private_root.iterdir()} != {"run.lock"}:
            raise Program007MetadataError("Program 007 persistent evidence already exists")
        key_id, secret_key = _load_explicit_credentials(environ)
        client = _AlpacaMetadataClient(key_id, secret_key, transport)
        budget = _Budget()

        def writer(key: str, payload: bytes) -> None:
            _append_persistent_evidence(private_root, key, payload)

        chains = tuple(
            _execute_chain(
                chain,
                budget,
                lambda intent, _intent_key: client.get(intent),
                writer,
            )
            for chain in frozen_request_chains()
        )
        transport.require_exhausted()
        result = MetadataQualificationResult(chains, _reconcile_chains(chains))
        observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        writer(
            "private-manifest.json",
            canonical_json(
                result.private_manifest(
                    status="MOCK-TRANSPORT-PERSISTENT-CONTRACT-PASS",
                    metadata_observation_as_of=observed_at,
                    synthetic_credential_loads=1,
                )
            ).encode(),
        )
        return result


def parse_metadata_page(body: bytes) -> tuple[tuple[CanonicalAction, ...], str | None]:
    payload = _json_object(body, "Program 007 metadata response")
    if set(payload) != {"corporate_actions", "next_page_token"}:
        raise Program007MetadataError("Program 007 metadata response schema differs")
    next_token = payload["next_page_token"]
    if next_token is not None and (not isinstance(next_token, str) or not next_token):
        raise Program007MetadataError("Program 007 metadata next_page_token is malformed")
    grouped = _mapping(payload["corporate_actions"], "corporate_actions")
    unknown_arrays = set(grouped) - set(_CONTRACT_BY_ARRAY)
    if unknown_arrays:
        raise Program007MetadataError(
            f"Program 007 metadata has unknown event arrays: {sorted(unknown_arrays)}"
        )
    actions: list[CanonicalAction] = []
    seen_ids: set[str] = set()
    for array_name, raw_events in grouped.items():
        contract = _CONTRACT_BY_ARRAY[array_name]
        for raw_event in _sequence(raw_events, array_name):
            action = normalize_event(contract, _mapping(raw_event, contract.event_type))
            if action.provider_event_id in seen_ids:
                raise Program007MetadataError("Program 007 metadata contains a duplicate event")
            seen_ids.add(action.provider_event_id)
            actions.append(action)
            if len(actions) > 1000:
                raise Program007MetadataError("Program 007 metadata page exceeds 1000 events")
    return tuple(sorted(actions, key=lambda action: action.sort_key)), next_token


def normalize_event(contract: EventContract, event: Mapping[str, Any]) -> CanonicalAction:
    keys = set(event)
    if not contract.required <= keys <= contract.allowed:
        raise Program007MetadataError(f"Program 007 {contract.event_type} schema differs")
    event_id = _uuid(event["id"])
    dates: dict[str, date] = {}
    numbers: dict[str, Decimal] = {}
    for key, value in event.items():
        if key in _DATE_FIELDS:
            dates[key] = _date(value, key)
        elif key in _NUMBER_FIELDS:
            numbers[key] = _decimal(value, key)
        elif key in {"special", "foreign"}:
            if type(value) is not bool:
                raise Program007MetadataError(f"Program 007 {key} is invalid")
        elif key == "stock_movements":
            _validate_stock_movements(value)
        elif key != "id" and not isinstance(value, str):
            raise Program007MetadataError(f"Program 007 {key} is invalid")
    for key in contract.required - _DATE_FIELDS - _NUMBER_FIELDS - {"special", "foreign"}:
        if key != "id" and (not isinstance(event[key], str) or not event[key]):
            raise Program007MetadataError(f"Program 007 required {key} is empty")
    if event.get("sub_type") not in {None, "interest", "return_of_capital"}:
        raise Program007MetadataError("Program 007 cash-dividend subtype is invalid")
    if event.get("lottery_type") not in {None, "original", "supplemental"}:
        raise Program007MetadataError("Program 007 partial-call lottery type is invalid")
    if (
        contract.event_type == "capital_gains_distribution"
        and not {
            "long_term_rate",
            "short_term_rate",
        }
        & keys
    ):
        raise Program007MetadataError("Program 007 capital-gains rates are missing")

    process_date = dates["process_date"]
    if not PROCESS_START <= process_date <= PROCESS_END:
        raise Program007MetadataError("Program 007 process date is outside the frozen query bounds")

    symbols, cusips, isins = _identifiers(event)
    target_symbols = _target_symbols(symbols, cusips)
    if not target_symbols:
        raise Program007MetadataError("Program 007 metadata contains a foreign identity")
    _require_consistent_identities(contract.event_type, event)

    old_units: Fraction | None = None
    new_units: Fraction | None = None
    exact_factor: Fraction | None = None
    classification = "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION"
    if contract.event_type in {"forward_split", "reverse_split"}:
        old_units = _positive_fraction(numbers["old_rate"], "old_rate")
        new_units = _positive_fraction(numbers["new_rate"], "new_rate")
        exact_factor = new_units / old_units
        classification = "DETERMINISTIC-TRANSFORMABLE"
        if contract.event_type == "reverse_split" and (
            event["new_cusip"] != event["old_cusip"]
            or event.get("new_symbol") not in {None, "", event["symbol"]}
        ):
            classification = "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION"
            exact_factor = None
    elif contract.event_type in _NON_UNIT_TYPES:
        classification = "NON-UNIT-METADATA"
    elif contract.event_type == "name_change" and (
        event["old_symbol"] == event["new_symbol"] and event["old_cusip"] == event["new_cusip"]
    ):
        classification = "IDENTITY-METADATA-NO-BREAK"

    effective_date = dates.get(contract.effective_field) if contract.effective_field else None
    provider_rates = tuple(sorted((key, _decimal_text(value)) for key, value in numbers.items()))
    return CanonicalAction(
        provider_event_id=event_id,
        action_type=contract.event_type,
        symbols=symbols,
        cusips=cusips,
        isins=isins,
        target_symbols=target_symbols,
        subtype=event.get("sub_type") or event.get("lottery_type"),
        process_date=process_date,
        announcement_date=None,
        effective_date=effective_date,
        effective_date_field=contract.effective_field,
        record_date=dates.get("record_date"),
        payable_date=dates.get("payable_date"),
        provider_rates=provider_rates,
        old_units=old_units,
        new_units=new_units,
        exact_factor=exact_factor,
        classification=classification,
        source_identity=fingerprint(
            {"provider": "alpaca", "event_type": contract.event_type, "event": event}
        ),
    )


def generate_successor_ledger_candidate(
    result: MetadataQualificationResult,
    public_ledger: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Build an in-memory discrepancy report against the authoritative public ledger."""
    if type(result) is not MetadataQualificationResult:
        raise Program007MetadataError("Program 007 metadata result is invalid")
    validate_action_ledger(public_ledger)
    applicable: list[CanonicalAction] = []
    for action in result.events:
        if action.classification in {"NON-UNIT-METADATA", "IDENTITY-METADATA-NO-BREAK"}:
            continue
        if action.effective_date is None:
            raise Program007MetadataError(
                f"Program 007 {action.action_type} has no unambiguous effective date"
            )
        if not COVERAGE_START <= action.effective_date <= COVERAGE_END:
            continue
        if action.classification != "DETERMINISTIC-TRANSFORMABLE":
            raise Program007MetadataError(
                f"Program 007 {action.action_type} is not deterministically transformable"
            )
        applicable.append(action)

    by_symbol = {
        symbol: tuple(action for action in applicable if symbol in action.target_symbols)
        for symbol in SYMBOLS
    }
    for symbol in POSITIVE_CONTROLS:
        controls = by_symbol[symbol]
        if (
            len(controls) != 1
            or controls[0].action_type != "forward_split"
            or controls[0].effective_date != date(2025, 12, 5)
            or controls[0].exact_factor != Fraction(2, 1)
        ):
            raise Program007MetadataError(f"Program 007 positive control failed for {symbol}")
    unexpected = sorted(symbol for symbol in NEGATIVE_CONTROLS if by_symbol[symbol])
    if unexpected:
        raise Program007MetadataError(
            f"Program 007 negative controls require investigation: {unexpected}"
        )

    symbols = [
        {
            "symbol": symbol,
            "cusip": IDENTITIES[symbol],
            "coverage_start": COVERAGE_START.isoformat(),
            "coverage_end": COVERAGE_END.isoformat(),
            "conclusion": (
                "APPLICABLE-ACTIONS-RECORDED"
                if by_symbol[symbol]
                else "NO-ADDITIONAL-APPLICABLE-ACTION-OBSERVED-AS-OF-QUERY"
            ),
            "provider_event_ids": [action.provider_event_id for action in by_symbol[symbol]],
        }
        for symbol in SYMBOLS
    ]
    candidate: dict[str, Any] = {
        "schema_version": "program-007-structured-action-ledger-candidate-v1",
        "program_id": PROGRAM_ID,
        "status": "SYNTHETIC-CORROBORATION-CANDIDATE-NOT-AUTHORITATIVE",
        "identity_history_status": IDENTITY_HISTORY_STATUS,
        "source_finality_status": SOURCE_FINALITY_STATUS,
        "coverage": {
            "start": COVERAGE_START.isoformat(),
            "end": COVERAGE_END.isoformat(),
        },
        "metadata_contract": {
            "provider": "Alpaca Historical Corporate Actions API",
            "endpoint": ENDPOINT,
            "query_chain_identities": [chain.chain.identity for chain in result.chains],
            "response_hashes": sorted(
                page.response_sha256 for chain in result.chains for page in chain.pages
            ),
            "data_quality": "complete",
            "region": "us",
            "query_end": METADATA_QUERY_END.isoformat(),
            "negative_event_completeness_proved": False,
        },
        "public_corroboration": {
            "ledger_id": public_ledger["ledger_id"],
            "ledger_fingerprint": public_ledger["ledger_fingerprint"],
        },
        "symbols": symbols,
        "actions": [
            action.ledger_record() for action in sorted(applicable, key=lambda x: x.sort_key)
        ],
        "authority": dict(_AUTHORITY),
    }
    candidate["ledger_fingerprint"] = fingerprint(candidate)
    return candidate


def _prepare_private_root(repository: Path) -> Path:
    if not isinstance(repository, Path):
        raise Program007MetadataError("Program 007 repository root is invalid")
    repository = repository.resolve()
    if not repository.is_dir():
        raise Program007MetadataError("Program 007 repository root is absent")
    private_root = repository / PRIVATE_ROOT
    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if private_root.resolve() != private_root.absolute():
        raise Program007MetadataError("Program 007 private evidence root must not use symlinks")
    if stat.S_IMODE(private_root.stat().st_mode) & 0o077:
        raise Program007MetadataError("Program 007 private evidence root is not private")
    return private_root


def _load_explicit_credentials(environ: Mapping[str, str]) -> tuple[str, str]:
    if not isinstance(environ, Mapping) or environ is os.environ:
        raise Program007MetadataError(
            "Program 007 mock execution requires an explicit synthetic environment"
        )
    values = tuple(environ.get(name) for name in CREDENTIAL_NAMES)
    if any(not isinstance(value, str) or not value for value in values):
        raise Program007MetadataError(
            "Program 007 synthetic environment lacks the frozen credential names"
        )
    key_id, secret_key = values
    assert isinstance(key_id, str) and isinstance(secret_key, str)
    return key_id, secret_key


def _append_persistent_evidence(root: Path, key: str, payload: bytes) -> None:
    if type(key) is not str or _EVIDENCE_KEY.fullmatch(key) is None or type(payload) is not bytes:
        raise Program007MetadataError("Program 007 persistent evidence entry is invalid")
    path = root / key
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError:
        raise Program007MetadataError(
            f"Program 007 persistent evidence already exists: {key}"
        ) from None
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(root, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _validate_http_request(request: Request) -> None:
    parsed = urlsplit(request.full_url)
    if (
        request.get_method() != "GET"
        or parsed.scheme != "https"
        or parsed.hostname != "data.alpaca.markets"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1/corporate-actions"
        or parsed.fragment
    ):
        raise Program007MetadataError("Program 007 metadata request endpoint differs")


def _execute_chain(
    chain: RequestChain,
    budget: _Budget,
    response_for: Callable[[RequestIntent, str], RawResponse | None],
    append_evidence: Callable[[str, bytes], None],
) -> ChainResult:
    events: list[CanonicalAction] = []
    pages: list[PageEvidence] = []
    seen_event_ids: set[str] = set()
    seen_tokens: set[str] = set()
    incoming_token: str | None = None
    for page_index in range(1, chain.maximum_pages + 1):
        budget.reserve_request()
        intent = RequestIntent(
            chain_id=chain.chain_id,
            chain_identity=chain.identity,
            page_index=page_index,
            url=chain.url(incoming_token),
            incoming_page_token=incoming_token,
        )
        prefix = f"{chain.chain_id}-{page_index:02d}"
        intent_key = f"{prefix}.intent.json"
        append_evidence(intent_key, canonical_json(intent).encode())
        response = response_for(intent, intent_key)
        if response is None:
            raise Program007MetadataError(
                "Program 007 metadata transport is ambiguous; zero-retry use is consumed"
            )
        body_key = f"{prefix}.body"
        retained_body = response.body[: MAXIMUM_RESPONSE_PAGE_BYTES + 1]
        append_evidence(body_key, retained_body)
        response_sha256 = hashlib.sha256(response.body).hexdigest()
        append_evidence(
            f"{prefix}.receipt.json",
            canonical_json(
                {
                    "status": response.status,
                    "response_bytes": len(response.body),
                    "retained_response_bytes": len(retained_body),
                    "response_truncated": len(retained_body) != len(response.body),
                    "response_sha256": response_sha256,
                }
            ).encode(),
        )
        budget.accept_response(response.body)
        if response.status == 403:
            raise MetadataAccessError("METADATA-ACCESS-FAIL: Alpaca entitlement returned HTTP 403")
        if 300 <= response.status < 400:
            raise Program007MetadataError("Program 007 metadata redirect attempt rejected")
        if response.status in {400, 401, 429, 500}:
            raise MetadataAccessError(
                f"METADATA-ACCESS-FAIL: Alpaca returned HTTP {response.status}"
            )
        if response.status != 200:
            raise Program007MetadataError(
                f"Program 007 metadata returned unexpected HTTP {response.status}"
            )
        page_events, outgoing_token = parse_metadata_page(response.body)
        duplicates = seen_event_ids & {event.provider_event_id for event in page_events}
        if duplicates:
            raise Program007MetadataError("Program 007 metadata repeats an event across pages")
        seen_event_ids.update(event.provider_event_id for event in page_events)
        events.extend(page_events)
        pages.append(
            PageEvidence(
                chain_id=chain.chain_id,
                chain_identity=chain.identity,
                page_index=page_index,
                request_url=intent.url,
                incoming_page_token=incoming_token,
                outgoing_page_token=outgoing_token,
                response_sha256=response_sha256,
                response_bytes=len(response.body),
                event_count=len(page_events),
            )
        )
        if outgoing_token is None:
            return ChainResult(
                chain,
                tuple(sorted(events, key=lambda action: action.sort_key)),
                tuple(pages),
            )
        if outgoing_token in seen_tokens:
            raise Program007MetadataError("Program 007 metadata pagination token repeats")
        seen_tokens.add(outgoing_token)
        incoming_token = outgoing_token
    raise Program007MetadataError("Program 007 metadata pagination exceeds four pages")


def _reconcile_chains(chains: tuple[ChainResult, ...]) -> tuple[CanonicalAction, ...]:
    if tuple(chain.chain.chain_id for chain in chains) != ("symbols", "cusips"):
        raise Program007MetadataError("Program 007 metadata query chains are incomplete")
    by_chain = [{action.provider_event_id: action for action in chain.events} for chain in chains]
    relevant_ids = [
        {event_id for event_id, action in events.items() if action.action_type in _RELEVANT_TYPES}
        for events in by_chain
    ]
    if relevant_ids[0] != relevant_ids[1]:
        raise Program007MetadataError("Program 007 symbol/CUSIP event inventories differ")
    combined: dict[str, CanonicalAction] = {}
    for events in by_chain:
        for event_id, action in events.items():
            existing = combined.get(event_id)
            if existing is not None and existing.source_identity != action.source_identity:
                raise Program007MetadataError("Program 007 duplicate event content differs")
            combined[event_id] = action
    return tuple(sorted(combined.values(), key=lambda action: action.sort_key))


def _identifiers(
    event: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    symbols: set[str] = set()
    cusips: set[str] = set()
    isins: set[str] = set()
    for key, value in event.items():
        if not isinstance(value, str) or not value:
            continue
        if key == "symbol" or key.endswith("_symbol"):
            symbols.add(value)
        elif key == "cusip" or key.endswith("_cusip"):
            cusips.add(value)
        elif key == "isin" or key.endswith("_isin"):
            isins.add(value)
    movements = event.get("stock_movements")
    if isinstance(movements, list):
        for raw_movement in movements:
            movement = _mapping(raw_movement, "reorganization stock movement")
            symbols.add(_string(movement["symbol"], "movement symbol"))
            cusips.add(_string(movement["cusip"], "movement CUSIP"))
            if movement.get("isin"):
                isins.add(_string(movement["isin"], "movement ISIN"))
    return tuple(sorted(symbols)), tuple(sorted(cusips)), tuple(sorted(isins))


def _target_symbols(symbols: tuple[str, ...], cusips: tuple[str, ...]) -> tuple[str, ...]:
    by_cusip = {cusip: symbol for symbol, cusip in IDENTITIES.items()}
    return tuple(
        sorted(
            ({symbol for symbol in symbols if symbol in IDENTITIES})
            | {by_cusip[cusip] for cusip in cusips if cusip in by_cusip}
        )
    )


def _require_consistent_identities(event_type: str, event: Mapping[str, Any]) -> None:
    pairs = [
        ("symbol", "cusip"),
        ("old_symbol", "old_cusip"),
        ("new_symbol", "new_cusip"),
        ("alternate_symbol", "alternate_cusip"),
        ("source_symbol", "source_cusip"),
        ("acquiree_symbol", "acquiree_cusip"),
        ("acquirer_symbol", "acquirer_cusip"),
    ]
    if event_type == "reverse_split":
        pairs.extend((("symbol", "old_cusip"), ("symbol", "new_cusip")))
    by_cusip = {cusip: symbol for symbol, cusip in IDENTITIES.items()}
    for symbol_key, cusip_key in pairs:
        symbol = event.get(symbol_key)
        cusip = event.get(cusip_key)
        if not isinstance(symbol, str) or not symbol or not isinstance(cusip, str) or not cusip:
            continue
        if (symbol in IDENTITIES and IDENTITIES[symbol] != cusip) or (
            cusip in by_cusip and by_cusip[cusip] != symbol
        ):
            raise Program007MetadataError("Program 007 symbol/CUSIP identity is inconsistent")


def _validate_stock_movements(value: Any) -> None:
    for raw in _sequence(value, "reorganization stock movements"):
        movement = _mapping(raw, "reorganization stock movement")
        if (
            not {"symbol", "cusip", "new_rate", "source_rate"}
            <= set(movement)
            <= {
                "symbol",
                "cusip",
                "isin",
                "new_rate",
                "source_rate",
            }
        ):
            raise Program007MetadataError("Program 007 stock-movement schema differs")
        _string(movement["symbol"], "movement symbol")
        _string(movement["cusip"], "movement CUSIP")
        _positive_fraction(_decimal(movement["new_rate"], "movement new_rate"), "new_rate")
        _positive_fraction(_decimal(movement["source_rate"], "movement source_rate"), "source_rate")


def _next_synthetic_response(
    source: SyntheticMetadataSource,
    intent: RequestIntent,
    intent_key: str,
) -> RawResponse | None:
    if type(source) is not SyntheticMetadataSource or type(intent) is not RequestIntent:
        raise Program007MetadataError("Program 007 synthetic metadata request is invalid")
    response_index = len(source._intents)
    source._intents.append(intent)
    source._intent_records_present.append(intent_key in source._evidence_keys)
    if response_index >= len(source._responses):
        raise Program007MetadataError("Program 007 synthetic metadata response is missing")
    return source._responses[response_index]


def _require_synthetic_responses_exhausted(source: SyntheticMetadataSource) -> None:
    if len(source._intents) != len(source._responses):
        raise Program007MetadataError("Program 007 synthetic metadata responses remain unused")


def _append_evidence(source: SyntheticMetadataSource, key: str, payload: bytes) -> None:
    if (
        type(source) is not SyntheticMetadataSource
        or type(key) is not str
        or type(payload) is not bytes
    ):
        raise Program007MetadataError("Program 007 metadata evidence entry is invalid")
    if key in source._evidence_keys:
        raise Program007MetadataError(f"Program 007 metadata evidence already exists: {key}")
    if source._evidence.closed:
        raise Program007MetadataError("Program 007 metadata evidence is closed")
    header = (
        canonical_json(
            {
                "key": key,
                "payload_bytes": len(payload),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
            }
        ).encode()
        + b"\n"
    )
    source._evidence.write(len(header).to_bytes(8, "big"))
    source._evidence.write(header)
    source._evidence.write(len(payload).to_bytes(8, "big"))
    source._evidence.write(payload)
    source._evidence.flush()
    os.fsync(source._evidence.fileno())
    source._evidence_keys.add(key)


def _json_object(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program007MetadataError(f"{label} is not valid JSON") from error
    if type(value) is not dict:
        raise Program007MetadataError(f"{label} must be an object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise Program007MetadataError(f"Program 007 {label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list | tuple):
        raise Program007MetadataError(f"Program 007 {label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Program007MetadataError(f"Program 007 {label} must be a non-empty string")
    return value


def _uuid(value: Any) -> str:
    raw = _string(value, "event ID")
    try:
        parsed = UUID(raw)
    except ValueError as error:
        raise Program007MetadataError("Program 007 event ID is not a UUID") from error
    if str(parsed) != raw:
        raise Program007MetadataError("Program 007 event ID is not canonical")
    return raw


def _date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise Program007MetadataError(f"Program 007 {label} must be a date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise Program007MetadataError(f"Program 007 {label} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise Program007MetadataError(f"Program 007 {label} must be canonical")
    return parsed


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise Program007MetadataError(f"Program 007 {label} must be an exact number")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise Program007MetadataError(f"Program 007 {label} is invalid") from error
    if not parsed.is_finite():
        raise Program007MetadataError(f"Program 007 {label} must be finite")
    return parsed


def _positive_fraction(value: Decimal, label: str) -> Fraction:
    if value <= 0:
        raise Program007MetadataError(f"Program 007 {label} must be positive")
    return Fraction(value)


def _decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _fraction_record(value: Fraction | None) -> Mapping[str, int] | None:
    if value is None:
        return None
    return {"numerator": value.numerator, "denominator": value.denominator}
