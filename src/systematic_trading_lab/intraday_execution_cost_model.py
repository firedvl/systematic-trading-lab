"""Frozen prospective SPY/QQQ execution-cost model."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .domain import Symbol
from .fingerprints import fingerprint

MODEL_ID = "intraday-execution-cost-model-001-v1"
MODEL_SCHEMA = "intraday-execution-cost-model-v1"
MODEL_RELATIVE_PATH = Path("config/research/intraday-execution-cost-model-001-v1.json")
REVIEWED_MODEL_SHA256 = "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af"
REGULATORY_FEE_MODEL_ID = "alpaca-us-equity-regulatory-fees-2026-07-20-v1"

_CENT = Decimal("0.01")
_BPS = Decimal("10000")
_SYMBOLS = (Symbol("QQQ"), Symbol("SPY"))
_AUTHORITY = {
    "strategy_results": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}


@dataclass(frozen=True)
class ExecutionCostScenario:
    scenario_id: str
    percentile: str | None
    slippage_bps_per_fill: Mapping[Symbol, Decimal]
    execution_delay_bars: int
    regulatory_fee_model_id: str | None

    def __post_init__(self) -> None:
        if not self.scenario_id or set(self.slippage_bps_per_fill) != set(_SYMBOLS):
            raise ValueError("execution-cost scenario identity differs")
        if self.execution_delay_bars < 1 or any(
            not value.is_finite() or value < 0 for value in self.slippage_bps_per_fill.values()
        ):
            raise ValueError("execution-cost scenario parameters are invalid")
        object.__setattr__(
            self,
            "slippage_bps_per_fill",
            MappingProxyType(dict(self.slippage_bps_per_fill)),
        )

    def fill_price(self, symbol: Symbol, market_price: Decimal, quantity: Decimal) -> Decimal:
        if market_price <= 0 or quantity == 0:
            raise ValueError("fill price requires a positive market price and nonzero quantity")
        direction = Decimal("1") if quantity > 0 else Decimal("-1")
        return market_price * (Decimal("1") + direction * self.slippage_bps_per_fill[symbol] / _BPS)


@dataclass(frozen=True)
class RegulatoryFill:
    executed_at: datetime
    trade_id: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    gross_notional: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.executed_at, datetime)
            or self.executed_at.tzinfo is None
            or self.executed_at.utcoffset() is None
        ):
            raise ValueError("regulatory fill execution timestamp must be timezone-aware")
        if not self.trade_id.strip():
            raise ValueError("regulatory fill identity is invalid")
        if self.side not in {"buy", "sell"} or any(
            not value.is_finite() or value <= 0 for value in (self.quantity, self.gross_notional)
        ):
            raise ValueError("regulatory fill is invalid")


@dataclass(frozen=True)
class DailyRegulatoryCharges:
    sec: Decimal
    taf: Decimal
    cat: Decimal

    @property
    def total(self) -> Decimal:
        return self.sec + self.taf + self.cat


@dataclass(frozen=True)
class RegulatoryFeeModel:
    model_id: str
    account_day_timezone: str
    sec_rate_per_dollar: Decimal
    taf_rate_per_share: Decimal
    taf_maximum_per_trade: Decimal
    cat_rate_per_share: Decimal

    def charges_for_account_day(
        self, account_day: date, fills: tuple[RegulatoryFill, ...]
    ) -> DailyRegulatoryCharges:
        timezone = ZoneInfo(self.account_day_timezone)
        if type(account_day) is not date or any(
            fill.executed_at.astimezone(timezone).date() != account_day for fill in fills
        ):
            raise ValueError("regulatory fills must belong to one account day")
        sells = tuple(fill for fill in fills if fill.side == "sell")
        sell_shares_by_trade: dict[str, Decimal] = {}
        for fill in sells:
            sell_shares_by_trade[fill.trade_id] = (
                sell_shares_by_trade.get(fill.trade_id, Decimal("0")) + fill.quantity
            )
        return DailyRegulatoryCharges(
            _ceil_cent(
                sum(
                    (fill.gross_notional * self.sec_rate_per_dollar for fill in sells),
                    Decimal("0"),
                )
            ),
            _ceil_cent(
                sum(
                    (
                        min(shares * self.taf_rate_per_share, self.taf_maximum_per_trade)
                        for shares in sell_shares_by_trade.values()
                    ),
                    Decimal("0"),
                )
            ),
            _ceil_cent(
                sum(
                    (fill.quantity * self.cat_rate_per_share for fill in fills),
                    Decimal("0"),
                )
            ),
        )


@dataclass(frozen=True)
class IntradayExecutionCostModel:
    path: Path
    sha256: str
    model_fingerprint: str
    payload: Mapping[str, Any]
    scenarios: Mapping[str, ExecutionCostScenario]
    regulatory_fees: RegulatoryFeeModel

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "scenarios", MappingProxyType(dict(self.scenarios)))


def load_intraday_execution_cost_model(
    repository: Path, *, data_home: Path | None = None
) -> IntradayExecutionCostModel:
    path = (repository / MODEL_RELATIVE_PATH).resolve()
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != REVIEWED_MODEL_SHA256:
        raise ValueError("intraday execution cost model SHA-256 differs")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("intraday execution cost model is invalid JSON") from error
    payload = _mapping(value, "execution cost model")
    if (
        payload.get("schema_version") != MODEL_SCHEMA
        or payload.get("cost_model_id") != MODEL_ID
        or payload.get("status") != "frozen-before-intraday-exposed-002-strategy-results"
        or payload.get("authority") != _AUTHORITY
    ):
        raise ValueError("intraday execution cost model identity differs")
    stored_fingerprint = _text(payload, "model_fingerprint")
    identity = dict(payload)
    del identity["model_fingerprint"]
    if fingerprint(identity) != stored_fingerprint:
        raise ValueError("intraday execution cost model fingerprint differs")

    evidence = _mapping(payload.get("calibration_evidence"), "calibration evidence")
    if (
        evidence.get("run_id") != "intraday-execution-calibration-001-v2"
        or evidence.get("feed") != "sip"
        or evidence.get("dataset_count") != 134
        or evidence.get("observation_count") != 80399
    ):
        raise ValueError("intraday execution calibration evidence differs")

    scenarios = _scenarios(payload)
    fees = _regulatory_fees(payload)
    model = IntradayExecutionCostModel(
        path,
        sha256,
        stored_fingerprint,
        payload,
        scenarios,
        fees,
    )
    if data_home is not None:
        verify_calibration_analysis(model, data_home)
    return model


def verify_calibration_analysis(model: IntradayExecutionCostModel, data_home: Path) -> Path:
    evidence = _mapping(model.payload.get("calibration_evidence"), "calibration evidence")
    analysis_fingerprint = _text(evidence, "analysis_fingerprint")
    path = (
        data_home.resolve()
        / _text(evidence, "run_id")
        / "analysis"
        / f"{analysis_fingerprint}.json"
    )
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != evidence.get("analysis_sha256"):
        raise ValueError("intraday execution calibration analysis SHA-256 differs")
    analysis = _mapping(json.loads(raw), "calibration analysis")
    sample = _mapping(analysis.get("sample"), "calibration sample")
    if (
        analysis.get("analysis_fingerprint") != analysis_fingerprint
        or analysis.get("feed") != evidence.get("feed")
        or analysis.get("quote_datasets_fingerprint") != evidence.get("quote_datasets_fingerprint")
        or sample.get("dataset_count") != evidence.get("dataset_count")
        or sample.get("observation_count") != evidence.get("observation_count")
        or sample.get("minimum_eligible_grid_coverage")
        != evidence.get("minimum_eligible_grid_coverage")
        or _mapping(sample.get("grid_exclusions"), "grid exclusions").get("total")
        != evidence.get("grid_exclusion_count")
        or sample.get("raw_crossed_market_count") != evidence.get("raw_crossed_market_count")
    ):
        raise ValueError("intraday execution calibration analysis identity differs")
    distributions = _mapping(analysis.get("distributions"), "calibration distributions")
    symbols = _mapping(distributions.get("symbol"), "symbol distributions")
    scenario_payloads = _mapping(model.payload.get("scenarios"), "scenarios")
    for scenario_name in ("normal", "stress_a", "stress_b"):
        scenario = _mapping(scenario_payloads.get(scenario_name), f"scenario {scenario_name}")
        percentile = _text(scenario, "percentile")
        source_values = _mapping(scenario.get("source_half_spread_bps"), "source spreads")
        for symbol in _SYMBOLS:
            distribution = _mapping(symbols.get(symbol.value), f"distribution {symbol.value}")
            half_spread = _mapping(distribution.get("half_spread_bps"), "half spread")
            if _decimal(source_values.get(symbol.value), "source spread") != _decimal(
                half_spread.get(percentile), "analysis spread"
            ):
                raise ValueError("intraday execution cost percentile source differs")
    return path


def _scenarios(payload: Mapping[str, Any]) -> dict[str, ExecutionCostScenario]:
    values = _mapping(payload.get("scenarios"), "scenarios")
    if set(values) != {"normal", "stress_a", "stress_b", "zero_cost_diagnostic"}:
        raise ValueError("intraday execution cost scenarios differ")
    expected = {
        "normal": ("p75", 1, REGULATORY_FEE_MODEL_ID),
        "stress_a": ("p95", 2, REGULATORY_FEE_MODEL_ID),
        "stress_b": ("p99", 3, REGULATORY_FEE_MODEL_ID),
        "zero_cost_diagnostic": (None, 1, None),
    }
    result: dict[str, ExecutionCostScenario] = {}
    for name, (percentile, delay, fee_id) in expected.items():
        item = _mapping(values.get(name), f"scenario {name}")
        raw_percentile = item.get("percentile")
        if raw_percentile != percentile:
            raise ValueError("intraday execution cost scenario percentile differs")
        configured = _symbol_decimals(item.get("slippage_bps_per_fill"), "slippage")
        source = _symbol_decimals(item.get("source_half_spread_bps"), "source spread")
        if percentile is None:
            if any(configured.values()) or any(source.values()):
                raise ValueError("zero-cost diagnostic has monetary costs")
        elif any(
            configured[symbol] != source[symbol].quantize(Decimal("0.01"), rounding=ROUND_CEILING)
            for symbol in _SYMBOLS
        ):
            raise ValueError("intraday execution cost scenario rounding differs")
        if (
            item.get("execution_delay_bars") != delay
            or _decimal(item.get("brokerage_commission_bps"), "commission") != 0
            or item.get("regulatory_fee_model_id") != fee_id
        ):
            raise ValueError("intraday execution cost scenario parameters differ")
        result[name] = ExecutionCostScenario(name, percentile, configured, delay, fee_id)
    for symbol in _SYMBOLS:
        if not (
            result["normal"].slippage_bps_per_fill[symbol]
            < result["stress_a"].slippage_bps_per_fill[symbol]
            < result["stress_b"].slippage_bps_per_fill[symbol]
        ):
            raise ValueError("intraday execution cost stresses are not stricter")
    return result


def _regulatory_fees(payload: Mapping[str, Any]) -> RegulatoryFeeModel:
    values = _mapping(payload.get("regulatory_fees"), "regulatory fees")
    sec = _mapping(values.get("sec_transaction_fee"), "SEC fee")
    taf = _mapping(values.get("finra_trading_activity_fee"), "TAF fee")
    cat = _mapping(values.get("finra_cat_fee"), "CAT fee")
    model = RegulatoryFeeModel(
        _text(values, "model_id"),
        _text(values, "account_day_timezone"),
        _decimal(sec.get("rate_per_dollar_of_executed_sell_notional"), "SEC rate"),
        _decimal(taf.get("rate_per_executed_share"), "TAF rate"),
        _decimal(taf.get("maximum_per_trade"), "TAF maximum"),
        _decimal(cat.get("rate_per_executed_equivalent_share"), "CAT rate"),
    )
    if model != RegulatoryFeeModel(
        REGULATORY_FEE_MODEL_ID,
        "America/New_York",
        Decimal("0.0000206"),
        Decimal("0.000195"),
        Decimal("9.79"),
        Decimal("0.000003"),
    ):
        raise ValueError("intraday regulatory fee schedule differs")
    return model


def _ceil_cent(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0:
        raise ValueError("fee value must be finite and non-negative")
    if value == 0:
        return Decimal("0")
    return value.quantize(_CENT, rounding=ROUND_CEILING)


def _symbol_decimals(value: object, label: str) -> dict[Symbol, Decimal]:
    item = _mapping(value, label)
    if set(item) != {symbol.value for symbol in _SYMBOLS}:
        raise ValueError(f"{label} symbols differ")
    return {symbol: _decimal(item[symbol.value], label) for symbol in _SYMBOLS}


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be text")
    return item


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ValueError(f"{label} must be decimal text")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be decimal text") from error
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result
