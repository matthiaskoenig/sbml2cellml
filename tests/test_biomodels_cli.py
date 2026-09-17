"""Tests of the `sbml2cellml-biomodels` command."""

import json
from pathlib import Path

import pytest

from sbml2cellml.biomodels import cli, runner
from sbml2cellml.biomodels.models import load_selection, write_selection
from sbml2cellml.testsuite.results import STAGES, CaseResult, StageResult, SuiteResult
from tests.biomodels_mocks import mock_downloads, write_comp_model


@pytest.fixture
def comp_path(tmp_path: Path) -> Path:
    return write_comp_model(tmp_path / "comp_model.xml")


@pytest.fixture(autouse=True)
def _mocks(monkeypatch: pytest.MonkeyPatch, comp_path: Path) -> None:
    mock_downloads(monkeypatch, runner, comp_path)


def test_cli_run_with_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    results_path = tmp_path / "results.json"
    report_path = tmp_path / "report.md"
    code = cli.main(
        [
            "run",
            "--ids",
            "BIOMD_A",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results_path),
            "--report",
            str(report_path),
        ]
    )
    assert code == 0
    assert results_path.is_file()
    assert report_path.is_file()
    out = capsys.readouterr().out
    assert "BIOMD_A" in out
    assert "reference: " in out


def test_cli_run_with_models_file(tmp_path: Path) -> None:
    models_path = tmp_path / "models.json"
    write_selection(models_path, ["BIOMD_A", "BIOMD_B"])
    results_path = tmp_path / "results.json"
    report_path = tmp_path / "report.md"
    code = cli.main(
        [
            "run",
            "--models",
            str(models_path),
            "--count",
            "1",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results_path),
            "--report",
            str(report_path),
        ]
    )
    assert code == 0
    data = json.loads(results_path.read_text(encoding="utf-8"))
    assert list(data["cases"]) == ["BIOMD_A"]


def test_cli_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "query_curated_ids", lambda: ["BIOMD_A", "BIOMD_B", "BIOMD_C"]
    )
    models_path = tmp_path / "models.json"
    code = cli.main(["update", "--models", str(models_path)])
    assert code == 0
    assert load_selection(models_path).models == ("BIOMD_A", "BIOMD_B", "BIOMD_C")

    code = cli.main(["update", "--models", str(models_path), "--count", "2"])
    assert code == 0
    assert load_selection(models_path).models == ("BIOMD_A", "BIOMD_B")


def test_cli_report(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"
    report_path = tmp_path / "report.md"
    code = cli.main(
        [
            "run",
            "--ids",
            "BIOMD_A",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results_path),
            "--report",
            str(report_path),
        ]
    )
    assert code == 0
    report_path.unlink()

    code = cli.main(
        ["report", "--results", str(results_path), "--output", str(report_path)]
    )
    assert code == 0
    assert report_path.is_file()
    assert "BioModels" in report_path.read_text(encoding="utf-8")


def test_cli_missing_models_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["run", "--models", str(tmp_path / "missing.json")])
    assert code == 1
    assert "missing.json" in capsys.readouterr().err


def test_cli_run_aborts_on_high_download_failure_rate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results_path = tmp_path / "results.json"
    report_path = tmp_path / "report.md"
    # two of three ids fail to download (BIOMD_A is served, the rest are
    # not), well above the 5% threshold
    code = cli.main(
        [
            "run",
            "--ids",
            "BIOMD_A,BAD_1,BAD_2",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results_path),
            "--report",
            str(report_path),
        ]
    )
    assert code == 1
    assert not results_path.is_file()
    assert not report_path.is_file()
    assert "download" in capsys.readouterr().err.lower()


def test_cli_run_aborts_when_no_cases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results_path = tmp_path / "results.json"
    report_path = tmp_path / "report.md"
    # BIOMD_B downloads fine but is skipped for using the comp package, so
    # no case is left to run
    code = cli.main(
        [
            "run",
            "--ids",
            "BIOMD_B",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results_path),
            "--report",
            str(report_path),
        ]
    )
    assert code == 1
    assert not results_path.is_file()
    assert not report_path.is_file()
    assert "no cases" in capsys.readouterr().err.lower()


def test_cli_run_prints_regressions_and_improvements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results_path = tmp_path / "results.json"
    report_path = tmp_path / "report.md"
    previous = SuiteResult(suite="biomodels", version="0.0.0")
    stages = {stage: StageResult("pass") for stage in STAGES}
    stages["roundtrip"] = StageResult("fail", "boom")
    previous.cases["BIOMD_A"] = CaseResult("BIOMD_A", [], [], stages, name="x")
    previous.to_json(results_path)

    code = cli.main(
        [
            "run",
            "--ids",
            "BIOMD_A",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results_path),
            "--report",
            str(report_path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "0 regressions" in out
    assert "1 improvements" in out
    assert "BIOMD_A roundtrip: fail -> pass" in out
