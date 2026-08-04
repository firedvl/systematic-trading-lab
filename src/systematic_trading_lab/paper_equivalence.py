"""Immutable replay, shadow, and paper action-plan comparisons."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .paper_observation import (
    PaperObservationCampaign,
    PaperObservationStore,
    _journal_matches,
    _parse_utc,
    _utc,
)

_MODES = {"replay", "shadow", "paper"}
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")


@dataclass(frozen=True, order=True)
class ActionTarget:
    symbol: str
    quantity: int

    def __post_init__(self) -> None:
        if _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("equivalence target symbol is invalid")
        if isinstance(self.quantity, bool) or self.quantity < 0:
            raise ValueError("equivalence target quantity is invalid")


@dataclass(frozen=True)
class ActionPlan:
    mode: str
    strategy_id: str
    strategy_version: str
    source_data_fingerprint: str
    configuration_fingerprint: str
    targets: tuple[ActionTarget, ...]
    evidence_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError("equivalence plan mode is invalid")
        _bounded("strategy ID", self.strategy_id)
        _bounded("strategy version", self.strategy_version)
        _sha256(self.source_data_fingerprint)
        _sha256(self.configuration_fingerprint)
        if (
            not self.targets
            or self.targets != tuple(sorted(self.targets))
            or len({target.symbol for target in self.targets}) != len(self.targets)
        ):
            raise ValueError("equivalence targets must be nonempty, sorted, and unique")
        if (
            not self.evidence_fingerprints
            or self.evidence_fingerprints != tuple(sorted(self.evidence_fingerprints))
            or len(set(self.evidence_fingerprints)) != len(self.evidence_fingerprints)
        ):
            raise ValueError("equivalence plan evidence must be nonempty, sorted, and unique")
        for value in self.evidence_fingerprints:
            _sha256(value)

    @property
    def plan_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class PaperEquivalenceRecord:
    comparison_id: str
    campaign_id: str
    replay: ActionPlan
    shadow: ActionPlan
    paper: ActionPlan
    paper_intent_keys: tuple[str, ...]
    reasons: tuple[str, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _bounded("comparison ID", self.comparison_id)
        _bounded("campaign ID", self.campaign_id)
        if (self.replay.mode, self.shadow.mode, self.paper.mode) != (
            "replay",
            "shadow",
            "paper",
        ):
            raise ValueError("equivalence record requires replay, shadow, and paper plans")
        if (
            not self.paper_intent_keys
            or self.paper_intent_keys != tuple(sorted(self.paper_intent_keys))
            or len(set(self.paper_intent_keys)) != len(self.paper_intent_keys)
        ):
            raise ValueError("paper equivalence intent keys must be nonempty, sorted, and unique")
        for value in self.paper_intent_keys:
            _bounded("paper intent key", value)
        if self.reasons != _comparison_reasons(self.replay, self.shadow, self.paper):
            raise ValueError("paper equivalence reasons differ from its plans")
        _utc(self.recorded_at)

    @property
    def equivalent(self) -> bool:
        return not self.reasons

    @property
    def record_fingerprint(self) -> str:
        return fingerprint(self)


class PaperEquivalenceStore(PaperObservationStore):
    """Store comparisons without risk or broker authority."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_equivalence_records (
                    comparison_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES paper_observation_campaigns(campaign_id),
                    record_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS paper_equivalence_records_no_update
                BEFORE UPDATE ON paper_equivalence_records BEGIN
                    SELECT RAISE(ABORT, 'paper equivalence records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_equivalence_records_no_delete
                BEFORE DELETE ON paper_equivalence_records BEGIN
                    SELECT RAISE(ABORT, 'paper equivalence records are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_equivalence(connection)

    def record(
        self,
        *,
        comparison_id: str,
        campaign_id: str,
        replay: ActionPlan,
        shadow: ActionPlan,
        paper_intent_keys: tuple[str, ...],
        recorded_at: datetime,
    ) -> PaperEquivalenceRecord:
        _utc(recorded_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaigns, records = self._verify_equivalence(connection)
            if campaign_id not in campaigns:
                raise KeyError(campaign_id)
            normalized_intent_keys = tuple(sorted(paper_intent_keys))
            paper = self._paper_plan(connection, normalized_intent_keys)
            existing = records.get(comparison_id)
            result = PaperEquivalenceRecord(
                comparison_id=comparison_id,
                campaign_id=campaign_id,
                replay=replay,
                shadow=shadow,
                paper=paper,
                paper_intent_keys=normalized_intent_keys,
                reasons=_comparison_reasons(replay, shadow, paper),
                recorded_at=existing.recorded_at if existing is not None else recorded_at,
            )
            if existing is not None:
                if existing != result:
                    raise JournalIntegrityError("paper equivalence comparison ID has other content")
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=recorded_at,
                event_type="paper-equivalence-recorded",
                entity_type="paper-equivalence",
                entity_id=comparison_id,
                payload=canonicalize(result),
            )
            connection.execute(
                "INSERT INTO paper_equivalence_records VALUES (?, ?, ?, ?)",
                (comparison_id, campaign_id, canonical_json(result), sequence),
            )
            connection.commit()
        return result

    def get(self, comparison_id: str) -> PaperEquivalenceRecord:
        _bounded("comparison ID", comparison_id)
        with self._connect() as connection:
            connection.execute("BEGIN")
            _, records = self._verify_equivalence(connection)
        try:
            return records[comparison_id]
        except KeyError:
            raise KeyError(comparison_id) from None

    def _paper_plan(
        self, connection: sqlite3.Connection, intent_keys: tuple[str, ...]
    ) -> ActionPlan:
        if not intent_keys or len(set(intent_keys)) != len(intent_keys):
            raise ValueError("paper equivalence intent keys must be nonempty and unique")
        intents = tuple(self._read_intent(connection, key) for key in intent_keys)
        first = intents[0]
        if any(
            intent.strategy_id != first.strategy_id
            or intent.strategy_version != first.strategy_version
            or intent.source_data_fingerprint != first.source_data_fingerprint
            or intent.configuration_fingerprint != first.configuration_fingerprint
            or intent.target_quantity is None
            for intent in intents
        ):
            raise JournalIntegrityError("paper equivalence intents do not form one quantity plan")
        targets_list: list[ActionTarget] = []
        for intent in intents:
            if intent.target_quantity is None:
                raise JournalIntegrityError(
                    "paper equivalence intents do not form one quantity plan"
                )
            targets_list.append(ActionTarget(intent.symbol, intent.target_quantity))
        targets = tuple(sorted(targets_list))
        return ActionPlan(
            mode="paper",
            strategy_id=first.strategy_id,
            strategy_version=first.strategy_version,
            source_data_fingerprint=first.source_data_fingerprint,
            configuration_fingerprint=first.configuration_fingerprint,
            targets=targets,
            evidence_fingerprints=tuple(sorted(intent.intent_fingerprint for intent in intents)),
        )

    def _verify_equivalence(
        self, connection: sqlite3.Connection
    ) -> tuple[dict[str, PaperObservationCampaign], dict[str, PaperEquivalenceRecord]]:
        campaigns, _ = self._verify_observations(connection)
        rows = connection.execute(
            "SELECT comparison_id, campaign_id, record_json, journal_sequence "
            "FROM paper_equivalence_records"
        ).fetchall()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'paper-equivalence-recorded'"
        ).fetchone()[0]
        if len(rows) != event_count:
            raise JournalIntegrityError("paper equivalence record count differs")
        records: dict[str, PaperEquivalenceRecord] = {}
        for row in rows:
            try:
                record = _decode_record(json.loads(row[2]))
                campaigns[record.campaign_id]
                expected_paper = self._paper_plan(connection, record.paper_intent_keys)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored paper equivalence record is invalid") from error
            if (
                record.paper != expected_paper
                or row[:3] != (record.comparison_id, record.campaign_id, canonical_json(record))
                or not _journal_matches(
                    connection,
                    int(row[3]),
                    record.recorded_at,
                    "paper-equivalence-recorded",
                    "paper-equivalence",
                    record.comparison_id,
                    canonical_json(record),
                )
            ):
                raise JournalIntegrityError("paper equivalence record differs from its evidence")
            records[record.comparison_id] = record
        return campaigns, records


def load_action_plan(path: Path, *, mode: str) -> ActionPlan:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "strategy_id",
            "strategy_version",
            "source_data_fingerprint",
            "configuration_fingerprint",
            "targets",
            "evidence_fingerprints",
        }:
            raise ValueError("action plan has an invalid shape")
        if value.pop("schema_version") != "paper-action-plan-v1":
            raise ValueError("action plan schema is unsupported")
        return _decode_plan({**value, "mode": mode})
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {mode} action plan: {path}") from error


def _comparison_reasons(*plans: ActionPlan) -> tuple[str, ...]:
    reasons: list[str] = []
    if len({(plan.strategy_id, plan.strategy_version) for plan in plans}) != 1:
        reasons.append("strategy-mismatch")
    if len({plan.source_data_fingerprint for plan in plans}) != 1:
        reasons.append("source-data-mismatch")
    if len({plan.configuration_fingerprint for plan in plans}) != 1:
        reasons.append("configuration-mismatch")
    if len({plan.targets for plan in plans}) != 1:
        reasons.append("target-mismatch")
    return tuple(reasons)


def _decode_record(value: object) -> PaperEquivalenceRecord:
    if not isinstance(value, dict):
        raise ValueError("paper equivalence record must be an object")
    try:
        return PaperEquivalenceRecord(
            **{
                **value,
                "replay": _decode_plan(value["replay"]),
                "shadow": _decode_plan(value["shadow"]),
                "paper": _decode_plan(value["paper"]),
                "paper_intent_keys": tuple(value["paper_intent_keys"]),
                "reasons": tuple(value["reasons"]),
                "recorded_at": _parse_utc(value["recorded_at"]),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("paper equivalence record is invalid") from error


def _decode_plan(value: object) -> ActionPlan:
    if not isinstance(value, dict):
        raise ValueError("action plan must be an object")
    try:
        return ActionPlan(
            **{
                **value,
                "targets": tuple(ActionTarget(**target) for target in value["targets"]),
                "evidence_fingerprints": tuple(value["evidence_fingerprints"]),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("action plan is invalid") from error


def _bounded(name: str, value: str) -> None:
    if not value or value != value.strip() or len(value) > 128:
        raise ValueError(f"{name} is invalid")


def _sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("equivalence fingerprint is invalid")
