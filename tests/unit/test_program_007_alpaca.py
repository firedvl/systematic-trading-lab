from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest

import systematic_trading_lab.program_007_alpaca as program_007
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import canonical_json, fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_LEDGER_PATH = _REPOSITORY / "config/research/program-007-unit-changing-action-ledger-v2.json"
_SCHEMA_PATH = (
    _REPOSITORY / "config/research/program-007-unit-changing-action-ledger-v2.schema.json"
)
_NYSE_MANIFEST_PATH = (
    _REPOSITORY / "config/research/program-007-nyse-corpax-retrieval-manifest-v1.json"
)
_PROPOSAL_PATH = (
    _REPOSITORY / "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json"
)
_IMPLEMENTATION_V1_PATH = (
    _REPOSITORY / "config/research/program-007-raw-source-contract-implementation-v1.json"
)
_IMPLEMENTATION_V2_PATH = (
    _REPOSITORY / "config/research/program-007-raw-source-contract-implementation-v2.json"
)
_IMPLEMENTATION_V3_PATH = (
    _REPOSITORY / "config/research/program-007-raw-source-contract-implementation-v3.json"
)
_IMPLEMENTATION_V4_PATH = (
    _REPOSITORY / "config/research/program-007-raw-source-contract-implementation-v4.json"
)
_IMPLEMENTATION_PATH = (
    _REPOSITORY / "config/research/program-007-raw-source-contract-implementation-v5.json"
)
_NOW = datetime(2026, 8, 28, 20, tzinfo=UTC)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _evidence_entries(source: program_007.SyntheticPageSource) -> dict[str, bytes]:
    with program_007._evidence_store(source) as store:
        return dict(store.entries)


def _evidence_record(source: program_007.SyntheticPageSource, key: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_evidence_entries(source)[key]))


def _ledger() -> dict[str, Any]:
    return _load(_LEDGER_PATH)


def _refingerprint(ledger: dict[str, Any]) -> None:
    unsigned = dict(ledger)
    unsigned.pop("ledger_fingerprint", None)
    ledger["ledger_fingerprint"] = fingerprint(unsigned)


def _bar(timestamp: datetime | str, **changes: object) -> dict[str, object]:
    value = (
        timestamp.isoformat().replace("+00:00", "Z")
        if isinstance(timestamp, datetime)
        else timestamp
    )
    row: dict[str, object] = {
        "t": value,
        "o": 100,
        "h": 101,
        "l": 99,
        "c": 100.5,
        "v": 10,
        "n": 2,
        "vw": 100.25,
    }
    row.update(changes)
    return row


def _body(rows: list[tuple[str, dict[str, object]]], token: str | None = None) -> bytes:
    bars: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol, row in rows:
        bars[symbol].append(row)
    return json.dumps(
        {"bars": dict(bars), "next_page_token": token},
        separators=(",", ":"),
    ).encode()


def _chain(
    *,
    chain_id: str = "synthetic",
    start: datetime = datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
    end: datetime = datetime(2025, 11, 26, 20, 55, tzinfo=UTC),
    symbols: tuple[str, ...] = ("SPY",),
    maximum_pages: int = 1,
) -> program_007.RequestChain:
    return program_007.RequestChain(chain_id, start, end, symbols, maximum_pages)


def _frozen_chain(chain_id: str) -> program_007.RequestChain:
    return next(
        chain
        for chain in program_007.frozen_request_chains(_PROPOSAL_PATH.read_bytes())
        if chain.chain_id == chain_id
    )


def _execute_frozen_chain(
    chain: program_007.RequestChain,
    page_source: program_007.SyntheticPageSource,
) -> program_007.QualificationResult:
    result = program_007._execute_chain(
        chain,
        page_source,
        program_007._Budget(),
        _NOW,
    )
    return program_007.QualificationResult((result,))


def _complete_rows(
    chain: program_007.RequestChain,
) -> list[tuple[str, dict[str, object]]]:
    timestamps = expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
    return [(symbol, _bar(timestamp)) for symbol in chain.symbols for timestamp in timestamps]


def _recursive_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_recursive_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value), set())
    return set()


def _synthetic_action(
    effective: str,
    old_shares: int,
    new_shares: int,
    action_type: str,
    *,
    transformable: bool = True,
) -> dict[str, object]:
    return {
        "symbol": "XLB",
        "effective_session": effective,
        "old_shares": old_shares,
        "new_shares": new_shares,
        "action_type": action_type,
        "transformable": transformable,
    }


def test_action_ledger_schema_hash_fingerprint_and_symbol_coverage() -> None:
    schema = _load(_SCHEMA_PATH)
    ledger = _ledger()
    assert (
        hashlib.sha256(_SCHEMA_PATH.read_bytes()).hexdigest() == ledger["schema_binding"]["sha256"]
    )
    assert schema["additionalProperties"] is False

    def assert_strict_objects(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
            for item in value.values():
                assert_strict_objects(item)
        elif isinstance(value, list):
            for item in value:
                assert_strict_objects(item)

    assert_strict_objects(schema)
    program_007.validate_action_ledger(ledger)
    assert ledger["ledger_fingerprint"] == (
        "0ec39d6f38d469e099862173ff710c0e737b39b464e233e291c9e9b20c089c25"
    )
    assert [item["symbol"] for item in ledger["symbols"]] == list(program_007.SYMBOLS)
    assert {item["symbol"] for item in ledger["actions"]} == {
        "XLB",
        "XLE",
        "XLK",
        "XLU",
        "XLY",
    }
    assert {
        item["symbol"]
        for item in ledger["symbols"]
        if item["conclusion"] == "NO-APPLICABLE-ACTION-FOUND"
    } == {"XLF", "XLI", "XLP", "XLRE", "XLV"}
    assert {
        item["symbol"] for item in ledger["symbols"] if item["conclusion"] == "COVERAGE-UNRESOLVED"
    } == {"IWM", "MDY", "SPY"}
    coverage = ledger["archive_coverage"]
    assert coverage["status"] == "INCOMPLETE"
    assert coverage["dataset_admission"] == "BLOCKED"
    assert coverage["unresolved_symbols"] == ["IWM", "MDY", "SPY"]
    assert coverage["nyse_corpax"]["forward_splits_in_scope"] is False
    assert coverage["nyse_corpax"]["target_record_count"] == 12
    assert all(value is False for value in ledger["authority"].values())


def test_nyse_retrieval_manifest_is_public_hash_only_evidence() -> None:
    ledger = _ledger()
    manifest = _load(_NYSE_MANIFEST_PATH)
    unsigned = dict(manifest)
    stored_fingerprint = unsigned.pop("manifest_fingerprint")
    assert stored_fingerprint == fingerprint(unsigned)
    assert manifest["entries_fingerprint"] == fingerprint(manifest["entries"])
    assert manifest["entry_count"] == len(manifest["entries"]) == 326
    binding = ledger["archive_coverage"]["nyse_corpax"]["retrieval_manifest_binding"]
    assert hashlib.sha256(_NYSE_MANIFEST_PATH.read_bytes()).hexdigest() == binding["sha256"]
    assert stored_fingerprint == binding["fingerprint"]
    assert manifest["entries_fingerprint"] == binding["entries_fingerprint"]
    assert all(
        set(entry)
        == {
            "kind",
            "start",
            "end",
            "response_sha256",
            "response_bytes",
            "reported_count",
            "result_count",
        }
        for entry in manifest["entries"]
    )


def test_non_authorizing_implementation_artifact_binds_exact_source_commit() -> None:
    assert hashlib.sha256(_IMPLEMENTATION_V1_PATH.read_bytes()).hexdigest() == (
        "69e0e40a83d9621a8e312c9d491264f5baf6a30d32a06405ecd705d6f728c662"
    )
    assert hashlib.sha256(_IMPLEMENTATION_V2_PATH.read_bytes()).hexdigest() == (
        "8f8183b8e18b6f5347e7a995924ef004b7c7d3b8c4c7a0d135368189a242bad4"
    )
    assert hashlib.sha256(_IMPLEMENTATION_V3_PATH.read_bytes()).hexdigest() == (
        "32a5fa3f18127cc95e98b9da1382590a855ed30d76e4de908c312cd6cea3774e"
    )
    assert hashlib.sha256(_IMPLEMENTATION_V4_PATH.read_bytes()).hexdigest() == (
        "4cec636042b8213d7ec15b5d6f72a702dffc36e7721e56486227f3931976e765"
    )
    implementation = _load(_IMPLEMENTATION_PATH)
    unsigned = dict(implementation)
    stored_fingerprint = unsigned.pop("implementation_fingerprint")
    assert stored_fingerprint == fingerprint(unsigned)
    binding = implementation["implementation_binding"]
    assert binding["implementation_root"] == fingerprint(binding["source_files"])
    for source in binding["source_files"]:
        contents = subprocess.run(
            ["git", "show", f"{binding['source_commit']}:{source['path']}"],
            cwd=_REPOSITORY,
            check=True,
            capture_output=True,
        ).stdout
        assert hashlib.sha256(contents).hexdigest() == source["sha256"]
    for name in (
        "proposal_binding",
        "action_ledger_binding",
        "action_schema_binding",
        "nyse_retrieval_manifest_binding",
    ):
        artifact = implementation[name]
        assert (
            hashlib.sha256((_REPOSITORY / artifact["path"]).read_bytes()).hexdigest()
            == (artifact["sha256"])
        )
    assert implementation["fresh_sample"]["expected_canonical_coordinates"] == 14_742
    assert implementation["ledger_disposition"]["dataset_admission"] == "BLOCKED"
    assert implementation["ledger_disposition"]["unresolved_symbols"] == ["IWM", "MDY", "SPY"]
    assert implementation["ledger_disposition"]["one_use_authority_proposal_eligible"] is False
    assert implementation["synthetic_verification"]["alpaca_or_market_data_provider_requests"] == 0
    assert implementation["synthetic_verification"]["strategy_calculations"] == 0
    assert all(value is False for value in implementation["authority"].values())


def test_action_ledger_mutation_unknown_action_and_inconsistent_ratio_fail_closed() -> None:
    ledger = _ledger()
    ledger["symbols"][0]["continuity_notes"] += " mutation"
    with pytest.raises(program_007.Program007Error, match="fingerprint"):
        program_007.validate_action_ledger(ledger)

    ledger = _ledger()
    ledger["archive_coverage"]["dataset_admission"] = "READY"
    _refingerprint(ledger)
    with pytest.raises(program_007.Program007Error, match="archive coverage disposition"):
        program_007.validate_action_ledger(ledger)

    ledger = _ledger()
    ledger["actions"][0]["action_type"] = "spin_off"
    _refingerprint(ledger)
    with pytest.raises(program_007.Program007Error, match="split ratio"):
        program_007.validate_action_ledger(ledger)

    ledger = _ledger()
    ledger["actions"][0]["new_shares"] = 1
    _refingerprint(ledger)
    with pytest.raises(program_007.Program007Error, match="split ratio"):
        program_007.validate_action_ledger(ledger)


def test_exact_volume_factors_cover_forward_reverse_and_sequential_actions() -> None:
    before = date(2025, 1, 2)
    middle = date(2025, 6, 2)
    after = date(2026, 1, 2)
    two_for_one = (_synthetic_action("2025-06-01", 1, 2, "forward_split"),)
    three_for_two = (_synthetic_action("2025-06-01", 2, 3, "forward_split"),)
    one_for_five = (_synthetic_action("2025-06-01", 5, 1, "reverse_split"),)
    sequential = (
        _synthetic_action("2025-02-01", 1, 2, "forward_split"),
        _synthetic_action("2025-05-01", 2, 3, "forward_split"),
        _synthetic_action("2025-09-01", 5, 1, "reverse_split"),
    )
    assert program_007.share_unit_factor_for_actions(two_for_one, "XLB", before, after) == 2
    assert program_007.share_unit_factor_for_actions(three_for_two, "XLB", before, after) == (
        Fraction(3, 2)
    )
    assert program_007.share_unit_factor_for_actions(one_for_five, "XLB", before, after) == (
        Fraction(1, 5)
    )
    assert program_007.share_unit_factor_for_actions(sequential, "XLB", before, after) == (
        Fraction(3, 5)
    )
    assert program_007.share_unit_factor_for_actions(sequential, "XLB", after, before) == (
        Fraction(5, 3)
    )
    assert program_007.share_unit_factor_for_actions(two_for_one, "XLB", middle, after) == 1


def test_ledger_normalization_uses_effective_session_boundary_and_exact_volume() -> None:
    ledger = _ledger()
    pre = date(2025, 11, 28)
    effective = date(2025, 12, 5)
    post = date(2025, 12, 15)
    actions = ledger["actions"]
    assert program_007.share_unit_factor_for_actions(actions, "XLB", pre, post) == 2
    assert program_007.share_unit_factor_for_actions(actions, "XLB", effective, post) == 1
    assert program_007.share_unit_factor_for_actions(actions, "XLB", post, pre) == Fraction(1, 2)
    assert program_007.share_unit_factor_for_actions(actions, "SPY", pre, post) == 1
    with pytest.raises(program_007.Program007Error, match="IWM, MDY, SPY"):
        program_007.require_action_ledger_admission(ledger)
    with pytest.raises(program_007.Program007Error, match="dataset admission is blocked"):
        program_007.share_unit_factor(ledger, "XLB", pre, post)
    with pytest.raises(program_007.Program007Error, match="dataset admission is blocked"):
        program_007.normalize_share_volume(Decimal("10.5"), ledger, "XLB", pre, post)


def test_ambiguous_and_inconsistent_synthetic_actions_fail_closed() -> None:
    with pytest.raises(program_007.Program007Error, match="not safely transformable"):
        program_007.share_unit_factor_for_actions(
            (_synthetic_action("2025-06-01", 1, 2, "spin_off"),),
            "XLB",
            date(2025, 1, 2),
            date(2026, 1, 2),
        )
    with pytest.raises(program_007.Program007Error, match="not safely transformable"):
        program_007.share_unit_factor_for_actions(
            (_synthetic_action("2025-06-01", 1, 2, "forward_split", transformable=False),),
            "XLB",
            date(2025, 1, 2),
            date(2026, 1, 2),
        )
    with pytest.raises(program_007.Program007Error, match="inconsistent"):
        program_007.share_unit_factor_for_actions(
            (_synthetic_action("2025-06-01", 2, 1, "forward_split"),),
            "XLB",
            date(2025, 1, 2),
            date(2026, 1, 2),
        )


def test_frozen_proposal_and_range_substitution_fail_before_source(tmp_path: Path) -> None:
    source = program_007.SyntheticPageSource(())

    proposal = _load(_PROPOSAL_PATH)
    proposal["request_plan"][0]["start"] = "2021-07-09T13:30:00Z"
    mutated = json.dumps(proposal, separators=(",", ":")).encode()
    with pytest.raises(program_007.Program007Error, match="proposal fingerprint differs"):
        program_007.execute_synthetic_qualification(mutated, source)

    with pytest.raises(program_007.Program007Error, match="proposal bytes differ"):
        program_007.execute_synthetic_qualification(_PROPOSAL_PATH.read_bytes() + b"\n", source)

    with pytest.raises(program_007.Program007Error, match="proposal must be exact bytes"):
        program_007.execute_synthetic_qualification(cast(Any, (_chain(),)), source)

    with pytest.raises(program_007.Program007Error, match="exact frozen request plan"):
        program_007._execute_qualification((_chain(),), source, observed_at=_NOW)

    with pytest.raises(program_007.Program007Error, match="outside the exact frozen plan"):
        program_007._execute_chain(_chain(), source, program_007._Budget(), _NOW)

    transport_calls = 0

    def transport_capable_source(intent: program_007.RequestIntent) -> program_007.RawResponse:
        nonlocal transport_calls
        transport_calls += 1
        raise AssertionError(f"unexpected source invocation: {intent.url}")

    with pytest.raises(program_007.Program007Error, match="synthetic responses only"):
        program_007.execute_synthetic_qualification(
            _PROPOSAL_PATH.read_bytes(), cast(Any, transport_capable_source)
        )

    clock_calls = 0

    def transport_capable_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        raise AssertionError("unexpected clock callback")

    timezone_calls = 0

    class TransportCapableTimezone(tzinfo):
        def utcoffset(self, value: datetime | None) -> timedelta:
            nonlocal timezone_calls
            timezone_calls += 1
            raise AssertionError(f"unexpected timezone callback: {value!r}")

        def dst(self, value: datetime | None) -> timedelta:
            nonlocal timezone_calls
            timezone_calls += 1
            raise AssertionError(f"unexpected timezone callback: {value!r}")

        def tzname(self, value: datetime | None) -> str:
            nonlocal timezone_calls
            timezone_calls += 1
            raise AssertionError(f"unexpected timezone callback: {value!r}")

    with pytest.raises(program_007.Program007Error, match="concrete UTC datetime"):
        program_007.execute_synthetic_qualification(
            _PROPOSAL_PATH.read_bytes(),
            source,
            observed_at=cast(Any, transport_capable_clock),
        )
    with pytest.raises(program_007.Program007Error, match="concrete UTC datetime"):
        program_007.execute_synthetic_qualification(
            _PROPOSAL_PATH.read_bytes(),
            source,
            observed_at=datetime(2026, 8, 28, 20, tzinfo=TransportCapableTimezone()),
        )

    mutations = (
        ("next_response", transport_capable_source),
        ("_private_root", tmp_path / "alternate-root"),
    )
    for name, value in mutations:
        with pytest.raises(AttributeError, match="immutable"):
            setattr(source, name, value)

    assert not source.intents
    assert transport_calls == 0
    assert clock_calls == 0
    assert timezone_calls == 0
    assert not any(source.private_root.iterdir())
    assert not any(tmp_path.iterdir())


def test_callback_capable_scalar_subclasses_are_rejected_without_invocation() -> None:
    callbacks: list[str] = []

    class CallbackBytes(bytes):
        def __len__(self) -> int:
            callbacks.append("len")
            raise AssertionError("unexpected bytes length callback")

        def decode(self, *args: object, **kwargs: object) -> str:
            callbacks.append("decode")
            raise AssertionError("unexpected bytes decode callback")

    class CallbackInt(int):
        def __eq__(self, other: object) -> bool:
            callbacks.append("eq")
            raise AssertionError(f"unexpected integer comparison callback: {other!r}")

    proposal_bytes = CallbackBytes(_PROPOSAL_PATH.read_bytes())
    response_bytes = CallbackBytes(b"{}")
    source = program_007.SyntheticPageSource(())

    with pytest.raises(program_007.Program007Error, match="proposal must be exact bytes"):
        program_007.execute_synthetic_qualification(proposal_bytes, source, observed_at=_NOW)
    with pytest.raises(program_007.Program007Error, match="response body must be bytes"):
        program_007.RawResponse(200, response_bytes)
    with pytest.raises(program_007.Program007Error, match="response status is invalid"):
        program_007.RawResponse(CallbackInt(200), b"{}")
    with pytest.raises(program_007.Program007Error, match="response body must be bytes"):
        program_007._Budget().accept_response(response_bytes)
    with pytest.raises(program_007.Program007Error, match="must be exact bytes"):
        program_007._load_json_object(response_bytes, "synthetic response")

    assert callbacks == []
    assert not source.intents
    assert not any(source.private_root.iterdir())


@pytest.mark.parametrize(
    "placement",
    ["chains", "chain", "requests", "pages", "request-file", "page"],
)
def test_synthetic_storage_rejects_internal_symlinks(placement: str, tmp_path: Path) -> None:
    chain = _frozen_chain("normal-2021-07-08")
    source = program_007.SyntheticPageSource(())
    root = source.private_root
    chains_root = root / "chains"
    chain_root = chains_root / chain.identity
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"unchanged")

    if placement == "chains":
        chains_root.symlink_to(outside, target_is_directory=True)
    elif placement == "chain":
        chains_root.mkdir()
        chain_root.symlink_to(outside, target_is_directory=True)
    elif placement in {"requests", "pages"}:
        chain_root.mkdir(parents=True)
        (chain_root / placement).symlink_to(outside, target_is_directory=True)
    elif placement == "request-file":
        (chain_root / "requests").mkdir(parents=True)
        redirected = outside / "redirected.json"
        redirected.write_bytes(b"unchanged")
        (chain_root / "requests/00001.json").symlink_to(redirected)
    else:
        (chain_root / "pages").mkdir(parents=True)
        (chain_root / "pages/00001").symlink_to(outside, target_is_directory=True)

    before = {path.name: path.read_bytes() for path in outside.iterdir()}
    with pytest.raises(program_007.Program007Error, match="foreign entry"):
        program_007.execute_synthetic_qualification(
            _PROPOSAL_PATH.read_bytes(), source, observed_at=_NOW
        )

    assert not source.intents
    assert {path.name: path.read_bytes() for path in outside.iterdir()} == before


def test_synthetic_storage_rejects_reflective_root_mutation(tmp_path: Path) -> None:
    source = program_007.SyntheticPageSource(())
    original = source.private_root
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    object.__setattr__(source, "_private_root", alternate)

    try:
        with pytest.raises(program_007.Program007Error, match="owned root"):
            program_007.execute_synthetic_qualification(
                _PROPOSAL_PATH.read_bytes(), source, observed_at=_NOW
            )
    finally:
        object.__setattr__(source, "_private_root", original)

    assert not source.intents
    assert not any(alternate.iterdir())


def test_synthetic_storage_rejects_replaced_root_inode() -> None:
    source = program_007.SyntheticPageSource(())
    root = source.private_root
    original = root.with_name(f"{root.name}-original")
    root.rename(original)
    root.mkdir()

    try:
        with pytest.raises(program_007.Program007Error, match="owned root"):
            program_007.execute_synthetic_qualification(
                _PROPOSAL_PATH.read_bytes(), source, observed_at=_NOW
            )
    finally:
        root.rmdir()
        original.rename(root)

    assert not source.intents


def test_evidence_descriptor_ignores_injected_external_directory(tmp_path: Path) -> None:
    source = program_007.SyntheticPageSource(())
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"unchanged")
    injected = source.private_root / "chains"

    with program_007._evidence_store(source) as store:
        outside.rename(injected)
        try:
            program_007._publish_record(store, "private-manifest.json", {"location": "evidence"})
            assert program_007._load_record(store, "private-manifest.json")["location"] == (
                "evidence"
            )
        finally:
            injected.rename(outside)

    assert sentinel.read_bytes() == b"unchanged"
    assert _evidence_record(source, "private-manifest.json")["location"] == "evidence"


def test_evidence_descriptor_never_reads_or_writes_injected_hard_link(tmp_path: Path) -> None:
    source = program_007.SyntheticPageSource(())
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"unchanged")
    injected = source.private_root / "private-manifest.json"

    with program_007._evidence_store(source) as store:
        injected.hardlink_to(outside)
        try:
            program_007._publish_record(store, "private-manifest.json", {"location": "evidence"})
            assert program_007._load_record(store, "private-manifest.json")["location"] == (
                "evidence"
            )
        finally:
            injected.unlink()

    assert outside.read_bytes() == b"unchanged"
    assert _evidence_record(source, "private-manifest.json")["location"] == "evidence"


@pytest.mark.parametrize("corruption", ["noncanonical", "invalid-base64"])
def test_evidence_log_rejects_corrupt_entries(corruption: str) -> None:
    source = program_007.SyntheticPageSource(())
    with program_007._evidence_store(source) as store:
        program_007._publish_record(store, "private-manifest.json", {"status": "retained"})

    descriptor = source._evidence.fileno()
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, 1024 * 1024)
    if corruption == "noncanonical":
        corrupted = b" " + raw
    else:
        entry = cast(dict[str, Any], json.loads(raw))
        entry["payload_base64"] = "!"
        unsigned = dict(entry)
        unsigned.pop("entry_fingerprint")
        entry["entry_fingerprint"] = fingerprint(unsigned)
        corrupted = (canonical_json(entry) + "\n").encode()
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    assert os.write(descriptor, corrupted) == len(corrupted)
    os.fsync(descriptor)

    with pytest.raises(program_007.Program007Error, match="evidence"):
        _evidence_entries(source)


def test_incomplete_retained_page_blocks_restart_before_source_use() -> None:
    chain = _frozen_chain("normal-2021-07-08")
    source = program_007.SyntheticPageSource(
        (program_007.RawResponse(200, _body(_complete_rows(chain))),)
    )
    chain_prefix = f"chains/{chain.identity}"
    body_key = f"{chain_prefix}/pages/00001/body.json"
    with program_007._evidence_store(source) as store:
        program_007._publish_record(store, f"{chain_prefix}/requests/00001.json", {})
        store.publish(body_key, b"retained")

    with pytest.raises(program_007.Program007Error, match="zero-retry"):
        _execute_frozen_chain(chain, source)

    assert not source.intents
    assert _evidence_entries(source)[body_key] == b"retained"


def test_frozen_raw_contract_and_full_14742_coordinate_shape() -> None:
    proposal_bytes = _PROPOSAL_PATH.read_bytes()
    chains = program_007.frozen_request_chains(proposal_bytes)
    assert len(chains) == 6
    assert sum(chain.maximum_pages for chain in chains) == 11
    assert (
        sum(
            len(expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES))
            * len(chain.symbols)
            for chain in chains
        )
        == 14_742
    )
    chain_by_id = {chain.chain_id: chain for chain in chains}
    pages: dict[tuple[str, str | None], bytes] = {}
    for chain in chains:
        rows = _complete_rows(chain)
        if chain.chain_id == "pagination-2023-05-16-to-2023-05-30":
            extended = ("SPY", _bar("2023-05-16T20:00:00Z"))
            pages[(chain.chain_id, None)] = _body([*rows[:9_999], extended], "page-2")
            pages[(chain.chain_id, "page-2")] = _body(rows[9_999:])
        else:
            pages[(chain.chain_id, None)] = _body(rows)

    responses = []
    for chain in chains:
        responses.append(program_007.RawResponse(200, pages[(chain.chain_id, None)]))
        if chain.chain_id == "pagination-2023-05-16-to-2023-05-30":
            responses.append(program_007.RawResponse(200, pages[(chain.chain_id, "page-2")]))
    source = program_007.SyntheticPageSource(responses)
    result = program_007.execute_synthetic_qualification(proposal_bytes, source, observed_at=_NOW)
    intents = source.intents
    assert result.response_count == len(intents) == 7
    assert all(source.intent_files_present)
    assert result.canonical_row_count == 14_742
    assert result.raw_row_count == 14_743
    assert [len(item.canonical_rows) for item in result.chains] == [
        1_014,
        1_014,
        1_014,
        10_140,
        546,
        1_014,
    ]
    assert intents[0].method == "GET"
    assert intents[0].redirects is False
    for intent in intents:
        query = parse_qs(urlparse(intent.url).query)
        assert query["feed"] == ["sip"]
        assert query["timeframe"] == ["5Min"]
        assert query["adjustment"] == ["raw"]
        assert query["sort"] == ["asc"]
        assert query["limit"] == ["10000"]
        assert query["asof"] == ["2026-07-31"]
        assert query["start"] == [
            chain_by_id[intent.chain_id].start.isoformat().replace("+00:00", "Z")
        ]
        assert query["end"] == [chain_by_id[intent.chain_id].end.isoformat().replace("+00:00", "Z")]

    summary = result.public_summary(_ledger()["ledger_fingerprint"])
    forbidden = {
        "bars",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "request_url",
        "incoming_page_token",
        "outgoing_page_token",
        "raw_file",
        "retrieved_at_utc",
        "provider_requests_performed",
    }
    assert not forbidden & _recursive_keys(summary)
    assert summary["canonical_row_count"] == 14_742
    assert summary["extended_hours_row_count"] == 1
    assert "private-manifest.json" in _evidence_entries(source)
    assert not any(source.private_root.iterdir())


def test_valid_extended_hours_are_retained_and_restart_never_rereads_source() -> None:
    chain = _frozen_chain("pagination-2023-05-16-to-2023-05-30")
    rows = [
        *(_complete_rows(chain)),
        ("SPY", _bar("2023-05-17T12:00:00Z")),
        ("SPY", _bar("2023-05-17T21:00:00Z")),
    ]
    bodies = {
        None: _body(rows[:9_999], "page-2"),
        "page-2": _body(rows[9_999:]),
    }
    source = program_007.SyntheticPageSource(
        (program_007.RawResponse(200, bodies[None]), program_007.RawResponse(200, bodies["page-2"]))
    )
    result = _execute_frozen_chain(chain, source)
    assert len(source.intents) == 2
    assert len(result.chains[0].raw_rows) == 10_142
    assert len(result.chains[0].canonical_rows) == 10_140
    assert result.chains[0].canonical_rows[0].timestamp == chain.start
    assert result.chains[0].canonical_rows[-1].timestamp == chain.end

    restarted = _execute_frozen_chain(chain, source)
    assert restarted == result
    assert len(source.intents) == 2
    entries = _evidence_entries(source)
    assert entries[f"chains/{chain.identity}/pages/00001/body.json"] == bodies[None]


@pytest.mark.parametrize(
    "case",
    [
        "weekend",
        "holiday",
        "out-of-bounds",
        "misaligned",
        "duplicate",
        "malformed-timestamp",
        "foreign-symbol",
        "corrupt-json",
    ],
)
def test_invalid_raw_pages_fail_after_exact_bytes_are_retained(case: str) -> None:
    chain = _frozen_chain("normal-2021-07-08")
    row = _bar(chain.start)
    rows = [("SPY", row)]
    pure_parser_case = False
    if case == "weekend":
        chain = _chain(
            start=datetime(2025, 11, 28, tzinfo=UTC),
            end=datetime(2025, 12, 1, 23, 55, tzinfo=UTC),
        )
        rows = [("SPY", _bar("2025-11-29T15:00:00Z"))]
        pure_parser_case = True
    elif case == "holiday":
        chain = _chain(
            start=datetime(2025, 7, 3, tzinfo=UTC),
            end=datetime(2025, 7, 7, 23, 55, tzinfo=UTC),
        )
        rows = [("SPY", _bar("2025-07-04T15:00:00Z"))]
        pure_parser_case = True
    elif case == "out-of-bounds":
        rows = [("SPY", _bar(chain.start - timedelta(minutes=5)))]
    elif case == "misaligned":
        rows = [("SPY", _bar(chain.start + timedelta(minutes=1)))]
    elif case == "duplicate":
        rows = [("SPY", row), ("SPY", row)]
    elif case == "malformed-timestamp":
        rows = [("SPY", _bar("not-a-timestamp"))]
    elif case == "foreign-symbol":
        rows = [("QQQ", row)]
    body = b"{" if case == "corrupt-json" else _body(rows)

    if pure_parser_case:
        with pytest.raises(program_007.Program007Error):
            program_007.parse_raw_page(body, chain)
        return

    source = program_007.SyntheticPageSource((program_007.RawResponse(200, body),))
    with pytest.raises(program_007.Program007Error):
        _execute_frozen_chain(chain, source)
    page_prefix = f"chains/{chain.identity}/pages/00001"
    assert _evidence_entries(source)[f"{page_prefix}/body.json"] == body
    validation = _evidence_record(source, f"{page_prefix}/validation.json")
    assert validation["raw_structural_status"] == "FAIL"


def test_missing_canonical_row_excludes_the_whole_session() -> None:
    chain = _frozen_chain("normal-2021-07-08")
    body = _body(_complete_rows(chain)[:-1])
    source = program_007.SyntheticPageSource((program_007.RawResponse(200, body),))
    with pytest.raises(program_007.Program007Error, match="whole session is ineligible"):
        _execute_frozen_chain(chain, source)
    outcome = _evidence_record(source, f"chains/{chain.identity}/validation.json")
    assert outcome["status"] == "FAIL"
    assert outcome["missing_coordinate_count"] == 1
    assert outcome["incomplete_sessions"] == ["2021-07-08"]


def test_forced_pagination_progression_and_token_cycle_rejection() -> None:
    chain = _frozen_chain("pagination-2023-05-16-to-2023-05-30")
    rows = _complete_rows(chain)
    responses = {
        None: _body(rows[:9_999], "page-2"),
        "page-2": _body(rows[9_999:]),
    }
    source = program_007.SyntheticPageSource(
        (
            program_007.RawResponse(200, responses[None]),
            program_007.RawResponse(200, responses["page-2"]),
        )
    )
    result = _execute_frozen_chain(chain, source)
    assert len(result.chains[0].pages) == 2
    assert parse_qs(urlparse(source.intents[1].url).query)["page_token"] == ["page-2"]

    cycle_responses = (
        program_007.RawResponse(200, body)
        for body in (
            _body(rows[:1], "loop"),
            _body(rows[1:2], "loop"),
        )
    )
    cycle_source = program_007.SyntheticPageSource(
        (
            next(cycle_responses),
            next(cycle_responses),
        )
    )
    with pytest.raises(program_007.Program007Error, match="token is repeated"):
        _execute_frozen_chain(chain, cycle_source)
    assert f"chains/{chain.identity}/pages/00002/body.json" in _evidence_entries(cycle_source)


def test_page_response_and_total_byte_ceilings_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _frozen_chain("pagination-2023-05-16-to-2023-05-30")
    rows = _complete_rows(chain)
    oversized = _body(rows)
    monkeypatch.setattr(program_007, "MAXIMUM_RESPONSE_PAGE_BYTES", len(oversized) - 1)
    page_source = program_007.SyntheticPageSource((program_007.RawResponse(200, oversized),))
    with pytest.raises(program_007.Program007Error, match="8 MiB page ceiling"):
        _execute_frozen_chain(chain, page_source)
    entries = _evidence_entries(page_source)
    assert f"chains/{chain.identity}/pages/00001/body.json" not in entries
    assert f"chains/{chain.identity}/requests/00001.json" in entries

    monkeypatch.setattr(program_007, "MAXIMUM_RESPONSE_PAGE_BYTES", 8 * 1024 * 1024)
    first = _body(rows[:1], "page-2")
    second = _body(rows[1:])
    monkeypatch.setattr(program_007, "MAXIMUM_DOWNLOADED_BYTES", len(first) + len(second) - 1)
    total_source = program_007.SyntheticPageSource(
        (program_007.RawResponse(200, first), program_007.RawResponse(200, second))
    )
    with pytest.raises(program_007.Program007Error, match="downloaded-byte ceiling"):
        _execute_frozen_chain(chain, total_source)
    entries = _evidence_entries(total_source)
    assert f"chains/{chain.identity}/pages/00001/body.json" in entries
    assert f"chains/{chain.identity}/pages/00002/body.json" not in entries


def test_page_and_response_count_ceilings_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _frozen_chain("pagination-2023-05-16-to-2023-05-30")
    rows = _complete_rows(chain)
    page_source = program_007.SyntheticPageSource(
        tuple(
            program_007.RawResponse(200, _body([rows[index]], f"more-{index}"))
            for index in range(chain.maximum_pages)
        )
    )
    with pytest.raises(program_007.Program007Error, match="page ceiling"):
        _execute_frozen_chain(chain, page_source)

    response_source = program_007.SyntheticPageSource(
        tuple(
            program_007.RawResponse(200, _body([rows[index]], f"more-{index + 1}"))
            for index in range(2)
        )
    )

    monkeypatch.setattr(program_007, "MAXIMUM_HTTP_RESPONSES", 1)
    with pytest.raises(program_007.Program007Error, match="response ceiling"):
        _execute_frozen_chain(chain, response_source)


def test_ambiguous_send_is_never_retried() -> None:
    chain = _frozen_chain("normal-2021-07-08")
    source = program_007.SyntheticPageSource((None,))

    with pytest.raises(program_007.Program007Error, match="zero-retry"):
        _execute_frozen_chain(chain, source)
    assert len(source.intents) == 1
    entries = _evidence_entries(source)
    assert f"chains/{chain.identity}/requests/00001.json" in entries
    assert not any(key.startswith(f"chains/{chain.identity}/pages/00001/") for key in entries)

    with pytest.raises(program_007.Program007Error, match="zero-retry"):
        _execute_frozen_chain(chain, source)
    assert len(source.intents) == 1


def test_dst_early_close_holiday_adjacency_and_multi_day_bar_opens() -> None:
    dst_chain = _chain(
        start=datetime(2025, 3, 7, 13, tzinfo=UTC),
        end=datetime(2025, 3, 10, 22, tzinfo=UTC),
    )
    grid = expected_bar_timestamps(dst_chain.start, dst_chain.end, Timeframe.FIVE_MINUTES)
    assert grid[0] == datetime(2025, 3, 7, 14, 30, tzinfo=UTC)
    assert grid[78] == datetime(2025, 3, 10, 13, 30, tzinfo=UTC)
    assert dst_chain.session_dates == (date(2025, 3, 7), date(2025, 3, 10))

    holiday_chain = _chain(
        start=datetime(2025, 7, 3, 13, tzinfo=UTC),
        end=datetime(2025, 7, 7, 22, tzinfo=UTC),
    )
    holiday_grid = expected_bar_timestamps(
        holiday_chain.start, holiday_chain.end, Timeframe.FIVE_MINUTES
    )
    assert holiday_chain.session_dates == (date(2025, 7, 3), date(2025, 7, 7))
    assert len([point for point in holiday_grid if point.date() == date(2025, 7, 3)]) == 42
    assert not any(point.date() == date(2025, 7, 4) for point in holiday_grid)


def test_secret_guard_rejects_tracked_program_007_private_raw_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_007_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    private_path = Path("program-007-private/pages/00001/body.json")
    private_path.parent.mkdir(parents=True)
    private_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [private_path])
    assert guard.main() == 1
    assert "private-market-data-path" in capsys.readouterr().err


def test_no_provider_client_credential_or_strategy_surface_exists() -> None:
    public_names = set(program_007.__dict__)
    assert (
        not {
            "AlpacaBarsClient",
            "read_credentials",
            "credential_preflight",
            "strategy",
            "backtest",
            "activate",
        }
        & public_names
    )
    assert program_007.AUTOMATIC_TRANSPORT_RETRIES == 0
    assert program_007.MAXIMUM_REQUESTS_PER_MINUTE == 120
