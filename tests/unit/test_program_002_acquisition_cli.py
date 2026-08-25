from __future__ import annotations

from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from systematic_trading_lab import program_002_acquisition_cli as cli
from systematic_trading_lab.program_002_acquisition import Program002AcquisitionError


def test_preflight_loads_plan_before_dedicated_credentials(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    order: list[str] = []
    repository = Path(__file__).resolve().parents[2]
    original = cli.load_plan  # type: ignore[attr-defined]

    def load(path: Path) -> object:
        order.append("plan")
        return original(path)

    def contract(_: object) -> None:
        order.append("contract")
        raise Program002AcquisitionError("blocked")

    monkeypatch.setattr(cli, "load_plan", load)
    monkeypatch.setattr(cli, "provider_contract_preflight", contract)
    assert cli.main(("--repository", str(repository), "preflight")) != 0
    assert order == ["plan", "contract"]
    assert "blocked" in capsys.readouterr().err


def test_cli_imports_no_forbidden_runtime_modules() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert not any(
        word in source for word in ("paper", "broker", "orders", "execution", "strategy")
    )
