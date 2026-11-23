"""Tests of the `sbml2cellml-physiome` command."""

import json
from pathlib import Path

import pytest

from sbml2cellml.physiome import cli, models
from sbml2cellml.physiome.models import PHYSIOME_URL, read_selection, write_selection
from sbml2cellml.testsuite.results import (
    CELLML_STAGES,
    CaseResult,
    StageResult,
    SuiteResult,
)
from tests.physiome_mocks import (
    EXPOSURE_MISSING,
    EXPOSURE_MULTI,
    mock_workspaces,
)


@pytest.fixture(autouse=True)
def _mocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_workspaces(monkeypatch, tmp_path / "workspaces")
    monkeypatch.setattr(
        cli, "exposure", lambda url: EXPOSURE_MULTI if url.endswith("multi") else None
    )


def test_cli_run_with_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    results_path = tmp_path / "results.json"
    report_path = tmp_path / "report.md"
    code = cli.main(
        [
            "run",
            "--ids",
            "multi",
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
    assert "multi libopencor=pass" in out
    assert "libopencor: 1 pass" in out
    result = SuiteResult.from_json(results_path)
    assert result.stages == CELLML_STAGES
    report = report_path.read_text(encoding="utf-8")
    assert "Physiome Model Repository" in report
    assert (report_path.parent / "images" / "physiome.svg").is_file()


def test_cli_run_with_an_unknown_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["run", "--ids", "unknown", "--work-dir", str(tmp_path / "work")])
    assert code == 1
    assert "has no CellML file" in capsys.readouterr().err


def test_cli_run_with_models_file(tmp_path: Path) -> None:
    models_path = tmp_path / "models.json"
    write_selection([EXPOSURE_MULTI, EXPOSURE_MISSING], models_path)
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
            str(tmp_path / "results.json"),
            "--report",
            str(tmp_path / "report.md"),
        ]
    )
    assert code == 0
    result = SuiteResult.from_json(tmp_path / "results.json")
    assert set(result.cases) == {"multi"}


def test_cli_run_without_cases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    models_path = tmp_path / "models.json"
    write_selection([EXPOSURE_MISSING], models_path)
    code = cli.main(
        [
            "run",
            "--models",
            str(models_path),
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(tmp_path / "results.json"),
        ]
    )
    assert code == 1
    assert "No cases to run" in capsys.readouterr().err


def test_cli_missing_models_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["run", "--models", str(tmp_path / "missing.json")])
    assert code == 1
    assert "Selection file does not exist" in capsys.readouterr().err


def test_cli_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "query_exposures", lambda: [EXPOSURE_MULTI])
    models_path = tmp_path / "models.json"
    assert cli.main(["update", "--models", str(models_path)]) == 0
    selection = read_selection(models_path)
    assert selection.models == (EXPOSURE_MULTI,)
    assert selection.source == PHYSIOME_URL
    assert json.loads(models_path.read_text(encoding="utf-8"))["models"][0][
        "commit"
    ] == (EXPOSURE_MULTI.commit)


def test_cli_update_of_a_failed_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail() -> list[models.Exposure]:
        raise models.PhysiomeError("listing failed")

    monkeypatch.setattr(cli, "query_exposures", fail)
    assert cli.main(["update", "--models", str(tmp_path / "models.json")]) == 1
    assert "listing failed" in capsys.readouterr().err


def _result() -> SuiteResult:
    stages = {stage: StageResult("pass") for stage in CELLML_STAGES}
    return SuiteResult(
        suite="physiome",
        version="0.0.0",
        cases={"multi": CaseResult("multi", [], [], stages, name="Multi")},
        stages=CELLML_STAGES,
    )


def test_cli_report(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"
    _result().to_json(results_path)
    output = tmp_path / "report.md"
    assert (
        cli.main(["report", "--results", str(results_path), "--output", str(output)])
        == 0
    )
    report = output.read_text(encoding="utf-8")
    assert "| multi | Multi |" in report
    assert (tmp_path / "images" / "physiome_dark.svg").is_file()


def test_cli_report_of_a_missing_results_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["report", "--results", str(tmp_path / "missing.json")])
    assert code == 1
    assert "Results file does not exist" in capsys.readouterr().err


def test_cli_run_prints_regressions_and_improvements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results_path = tmp_path / "results.json"
    previous = _result()
    previous.cases["multi"].stages["sbmlsim"] = StageResult("fail", "broken")
    previous.to_json(results_path)
    code = cli.main(
        [
            "run",
            "--ids",
            "multi",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results_path),
            "--report",
            str(tmp_path / "report.md"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "0 regressions" in out
    assert "1 improvements" in out
    assert "multi sbmlsim: fail -> pass" in out
