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


def test_revised_authority_is_checked_before_credentials(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    order: list[str] = []
    repository = Path(__file__).resolve().parents[2]

    monkeypatch.setattr(cli, "provider_contract_preflight", lambda _: order.append("contract"))

    def authority(_: object) -> None:
        order.append("authority")
        raise Program002AcquisitionError("blocked authority")

    monkeypatch.setattr(cli, "acquisition_authority_preflight", authority)
    monkeypatch.setattr(
        cli, "acquisition_credentials", lambda: (_ for _ in ()).throw(AssertionError())
    )
    assert cli.main(("--repository", str(repository), "preflight")) != 0
    assert order == ["contract", "authority"]
    assert "blocked authority" in capsys.readouterr().err


def test_exact_bar_and_quote_bounds_are_checked_before_credentials(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    repository = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(cli, "provider_contract_preflight", lambda _: None)
    monkeypatch.setattr(cli, "acquisition_authority_preflight", lambda _: None)
    monkeypatch.setattr(
        cli, "acquisition_credentials", lambda: (_ for _ in ()).throw(AssertionError())
    )

    def blocked_bounds(*_: object) -> None:
        raise Program002AcquisitionError("blocked bounds")

    monkeypatch.setattr(cli, "bar_segments", blocked_bounds)
    assert (
        cli.main(
            (
                "--repository",
                str(repository),
                "--data-home",
                str(tmp_path),
                "--acquisition-attempt-id",
                "program-002-repair-test",
                "--role",
                "exposed-block-1",
                "acquire-bars",
            )
        )
        != 0
    )

    monkeypatch.setattr(cli, "quote_segments", blocked_bounds)
    assert (
        cli.main(
            (
                "--repository",
                str(repository),
                "--data-home",
                str(tmp_path),
                "--acquisition-attempt-id",
                "program-002-repair-test",
                "acquire-quotes",
            )
        )
        != 0
    )


def test_cli_imports_no_forbidden_runtime_modules() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert not any(
        word in source for word in ("paper", "broker", "orders", "execution", "strategy")
    )
