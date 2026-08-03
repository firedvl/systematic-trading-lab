import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from systematic_trading_lab.execution import (
    DuplicateIntentError,
    ExecutionIntent,
    ExecutionStore,
    ExecutionStoreError,
    JournalIntegrityError,
)
from systematic_trading_lab.fingerprints import fingerprint


def _intent(**changes: object) -> ExecutionIntent:
    decision = datetime(2026, 8, 3, 20, tzinfo=UTC)
    intent = ExecutionIntent(
        idempotency_key="momentum-v1:SPY:2026-08-03",
        strategy_id="momentum",
        strategy_version="1",
        symbol="SPY",
        decision_timestamp=decision,
        target_weight=Decimal("0.5"),
        target_quantity=None,
        reason="daily target",
        source_data_fingerprint=fingerprint({"dataset": "fixture-v1"}),
        configuration_fingerprint=fingerprint({"window": 20}),
        reference_price=Decimal("631.25"),
        expires_at=decision + timedelta(hours=20),
    )
    return replace(intent, **cast(Any, changes))


def test_intent_validation_fails_closed() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _intent(target_quantity=4)
    with pytest.raises(ValueError, match="between zero and one"):
        _intent(target_weight=Decimal("1.01"))
    with pytest.raises(ValueError, match="uppercase"):
        _intent(symbol="spy")
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _intent(configuration_fingerprint="not-a-fingerprint")
    with pytest.raises(ValueError, match="UTC-aware"):
        _intent(decision_timestamp=datetime(2026, 8, 3, 20))


def test_store_deduplicates_exact_replay_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    received = datetime(2026, 8, 3, 21, tzinfo=UTC)
    receipt = ExecutionStore(path).record_intent(_intent(), received_at=received)

    restarted = ExecutionStore(path)
    assert restarted.record_intent(_intent(), received_at=received + timedelta(hours=1)) == receipt
    assert restarted.get_receipt(receipt.idempotency_key) == receipt
    assert restarted.get_intent(receipt.idempotency_key) == _intent()
    head = restarted.verify_journal()
    assert head.event_count == 1
    assert head.event_hash != "0" * 64


def test_store_rejects_changed_replay_and_new_expired_intent(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "execution.sqlite3")
    received = datetime(2026, 8, 3, 21, tzinfo=UTC)
    store.record_intent(_intent(), received_at=received)

    with pytest.raises(DuplicateIntentError, match="different intent"):
        store.record_intent(_intent(reference_price=Decimal("632")), received_at=received)
    with pytest.raises(ExecutionStoreError, match="expired"):
        store.record_intent(
            _intent(idempotency_key="expired", expires_at=received), received_at=received
        )
    assert store.verify_journal().event_count == 1


def test_rows_are_immutable_and_tampering_blocks_restart(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    store = ExecutionStore(path)
    store.record_intent(_intent(), received_at=datetime(2026, 8, 3, 21, tzinfo=UTC))

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE intents SET intent_json = '{}'")
        connection.execute("DROP TRIGGER journal_no_update")
        connection.execute("UPDATE journal SET payload_json = '{}' WHERE sequence = 1")

    with pytest.raises(JournalIntegrityError, match="hash chain"):
        ExecutionStore(path)

    truncated_path = tmp_path / "truncated.sqlite3"
    ExecutionStore(truncated_path).record_intent(
        _intent(), received_at=datetime(2026, 8, 3, 21, tzinfo=UTC)
    )
    with sqlite3.connect(truncated_path) as connection:
        connection.execute("DROP TRIGGER intents_no_delete")
        connection.execute("DROP TRIGGER journal_no_delete")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM journal")
    with pytest.raises(JournalIntegrityError, match="journal head"):
        ExecutionStore(truncated_path)
