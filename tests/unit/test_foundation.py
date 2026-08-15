import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import systematic_trading_lab.cli as cli
from systematic_trading_lab.cli import main, parser, run
from systematic_trading_lab.config import ConfigurationError, load_dotenv, load_settings
from systematic_trading_lab.datasets import DatasetService
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.paper_startup import initialize_paper_storage
from systematic_trading_lab.runtime_build import (
    RuntimeBuildAttestationIndeterminateError,
    RuntimeBuildVerificationError,
)
from systematic_trading_lab.validation import validate_records


def test_configuration_defaults_offline_and_rejects_live() -> None:
    settings = load_settings({})
    assert settings.mode.value == "offline"
    assert settings.broker_writes_allowed is False
    with pytest.raises(ConfigurationError, match="live trading is disabled"):
        load_settings({"TRADING_LAB_MODE": "live"})
    request_values = {
        "TRADING_LAB_MODE": "paper",
        "TRADING_LAB_PAPER_ACTIVATION_ID": "a" * 64,
        "TRADING_LAB_PAPER_CODE_COMMIT": "a" * 40,
    }
    requested = load_settings(request_values)
    assert requested.paper_write_request is not None
    assert requested.paper_write_request.request_fingerprint
    assert requested.broker_writes_allowed is True
    assert not load_settings({"TRADING_LAB_MODE": "paper"}).broker_writes_allowed
    for mode in ("offline", "research", "replay", "shadow", "live-disabled"):
        assert not load_settings({"TRADING_LAB_MODE": mode}).broker_writes_allowed
    with pytest.raises(ConfigurationError, match="full lowercase Git SHA-1"):
        load_settings({**request_values, "TRADING_LAB_PAPER_CODE_COMMIT": "not-a-commit"})
    with pytest.raises(ConfigurationError, match="activation ID and code commit"):
        load_settings({"TRADING_LAB_MODE": "paper", "TRADING_LAB_PAPER_ACTIVATION_ID": "a" * 64})
    with pytest.raises(ConfigurationError, match="requires paper mode"):
        load_settings({**request_values, "TRADING_LAB_MODE": "research"})


def test_doctor_does_not_load_unused_research_universe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "systematic_trading_lab.cli.load_research_universe",
        lambda: pytest.fail("universe must not load"),
    )

    assert (
        run(parser().parse_args(["doctor"]), load_settings({"TRADING_LAB_HOME": str(tmp_path)}))
        == 0
    )


def test_alpaca_import_accepts_an_explicit_daily_universe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(
        json.dumps(
            {
                "id": "test-expanded-universe-v1",
                "timeframe": "1d",
                "memberships": [
                    {
                        "symbol": symbol,
                        "start": "2000-01-01",
                        "end": None,
                        "source": f"https://example.com/{symbol.lower()}",
                    }
                    for symbol in ("SPY", "IEF")
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(cli, "AlpacaHistoricalProvider", lambda *_args: object())

    def import_from(
        _service: object,
        _provider: object,
        symbols: object,
        timeframe: object,
        requested: object,
        universe: object,
    ) -> SimpleNamespace:
        captured.update(
            symbols=symbols,
            timeframe=timeframe,
            requested=requested,
            universe=universe,
        )
        return SimpleNamespace(dataset_id="dataset", fingerprint="fingerprint", created=True)

    monkeypatch.setattr(DatasetService, "import_from", import_from)
    settings = load_settings({"TRADING_LAB_HOME": str(tmp_path), "TRADING_LAB_MODE": "research"})

    assert (
        run(
            parser().parse_args(
                [
                    "data",
                    "import-alpaca",
                    "--start",
                    "2020-07-27",
                    "--end",
                    "2020-07-28",
                    "--universe-config",
                    str(universe_path),
                ]
            ),
            settings,
        )
        == 0
    )
    assert tuple(str(symbol) for symbol in captured["symbols"]) == ("SPY", "IEF")
    assert captured["timeframe"] is Timeframe.DAILY
    assert captured["universe"].universe_id == "test-expanded-universe-v1"


def test_alpaca_import_rejects_policy_and_membership_ranges_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "AlpacaHistoricalProvider",
        lambda *_args: pytest.fail("provider must not be constructed"),
    )
    settings = load_settings({"TRADING_LAB_HOME": str(tmp_path), "TRADING_LAB_MODE": "research"})
    rapid_universe = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "research"
        / "rapid-004-seed-universe-v1.json"
    )

    with pytest.raises(ValueError, match="outside the universe acquisition range"):
        run(
            parser().parse_args(
                [
                    "data",
                    "import-alpaca",
                    "--start",
                    "2018-01-02",
                    "--end",
                    "2019-12-31",
                    "--universe-config",
                    str(rapid_universe),
                ]
            ),
            settings,
        )

    crossing = tmp_path / "crossing.json"
    crossing.write_text(
        json.dumps(
            {
                "id": "inception-crossing-v1",
                "timeframe": "1d",
                "memberships": [
                    {
                        "symbol": symbol,
                        "start": start,
                        "end": None,
                        "source": f"https://example.com/{symbol.lower()}",
                    }
                    for symbol, start in (("SPY", "1993-01-22"), ("QUAL", "2013-07-16"))
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="symbols lack full-range membership: QUAL"):
        run(
            parser().parse_args(
                [
                    "data",
                    "import-alpaca",
                    "--start",
                    "2010-01-04",
                    "--end",
                    "2010-01-05",
                    "--universe-config",
                    str(crossing),
                ]
            ),
            settings,
        )


def test_yahoo_import_rejects_policy_range_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "YahooHistoricalProvider",
        lambda: pytest.fail("provider must not be constructed"),
    )
    settings = load_settings({"TRADING_LAB_HOME": str(tmp_path), "TRADING_LAB_MODE": "research"})
    rapid_universe = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "research"
        / "rapid-004-seed-universe-v1.json"
    )

    with pytest.raises(ValueError, match="outside the universe acquisition range"):
        run(
            parser().parse_args(
                [
                    "data",
                    "import-yahoo",
                    "--start",
                    "2018-01-02",
                    "--end",
                    "2019-12-31",
                    "--universe-config",
                    str(rapid_universe),
                ]
            ),
            settings,
        )


def test_dotenv_loads_supported_values_without_overriding_environment(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "TRADING_LAB_MODE=research\n"
        "TRADING_LAB_HOME=.trading-lab\n"
        "APCA_API_KEY_ID=file-key\n"
        "APCA_API_SECRET_KEY='file-secret'\n",
        encoding="utf-8",
    )
    environment = {"APCA_API_KEY_ID": "process-key"}

    load_dotenv(path, environment)

    assert environment == {
        "TRADING_LAB_MODE": "research",
        "TRADING_LAB_HOME": ".trading-lab",
        "APCA_API_KEY_ID": "process-key",
        "APCA_API_SECRET_KEY": "file-secret",
    }


def test_dotenv_rejects_unknown_or_duplicate_entries(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("UNSUPPORTED_SETTING=value\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid .env entry"):
        load_dotenv(path, {})

    path.write_text("TRADING_LAB_MODE=paper\nTRADING_LAB_MODE=research\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate .env entry"):
        load_dotenv(path, {})


def test_cli_reports_malformed_database_as_configuration_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sqlite3

    with sqlite3.connect(tmp_path / "execution.sqlite3") as connection:
        connection.execute("CREATE TABLE paper_observations (invalid TEXT)")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADING_LAB_HOME", str(tmp_path))

    assert main(["paper", "assess-observation", "campaign"]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_maps_indeterminate_attestation_to_temporary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail(*args: object, **kwargs: object) -> int:
        raise RuntimeBuildAttestationIndeterminateError("attestation indeterminate")

    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(["doctor"]) == 75
    assert "attestation indeterminate" in capsys.readouterr().err


def test_cli_keeps_permanent_runtime_failure_at_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail(*args: object, **kwargs: object) -> int:
        raise RuntimeBuildVerificationError("runtime mismatch")

    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(["doctor"]) == 2


def test_paper_startup_cli_is_read_only_and_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = load_settings({"TRADING_LAB_HOME": str(tmp_path)})
    result = run(
        parser().parse_args(
            [
                "paper",
                "assess-startup",
                "--authorization",
                "missing",
                "--risk-config",
                "config/risk/alpaca-paper-v1.json",
            ]
        ),
        settings,
    )
    output = capsys.readouterr().out

    assert result == 1
    assert '"ready": false' in output
    assert "execution-database-missing-or-unsafe" in output
    assert not (tmp_path / "execution.sqlite3").exists()


def test_paper_storage_initialization_is_idempotent_and_non_authorizing(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    first = initialize_paper_storage(path)
    second = initialize_paper_storage(path)

    assert first.table_count == second.table_count
    assert first.journal_event_count == second.journal_event_count == 1
    assert first.authority_evidence_unchanged
    assert second.authority_evidence_unchanged


def test_canonical_fingerprint_normalizes_decimal_and_mapping_order() -> None:
    left = {"price": Decimal("100.00"), "symbol": "SPY"}
    right = {"symbol": "SPY", "price": Decimal("100")}
    assert fingerprint(left) == fingerprint(right)


def test_bar_rejects_impossible_prices_and_validation_quarantines_duplicate() -> None:
    with pytest.raises(ValueError, match="high"):
        OHLCVBar(
            Symbol("SPY"),
            datetime(2025, 1, 6, tzinfo=UTC),
            Decimal("100"),
            Decimal("99"),
            Decimal("98"),
            Decimal("100"),
            1,
        )
    record: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": "2025-01-06T00:00:00Z",
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100.5",
        "volume": 10,
    }
    result = validate_records([record, record], Timeframe.DAILY)
    assert not result.result.valid
    assert result.result.duplicate_intervals == ("SPY@2025-01-06T00:00:00+00:00",)
    assert result.result.quarantined_records == 1
