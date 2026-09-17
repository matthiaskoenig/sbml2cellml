"""Tests of the command line interface."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import libcellml
import libsbml
import pytest

from sbml2cellml import cellml2sbml
from sbml2cellml.cli import main, main_cellml2sbml
from tests.conftest import MODELS_DIR, TEST_MODEL_PATH


def test_convert_with_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "liver.cellml"
    code = main([str(MODELS_DIR / "glimepiride_liver.xml"), "-o", str(out)])
    assert code == 0
    assert out.is_file()
    assert str(out) in capsys.readouterr().out


def test_default_output_next_to_input(tmp_path: Path) -> None:
    sbml_path = tmp_path / "liver.xml"
    shutil.copy(MODELS_DIR / "glimepiride_liver.xml", sbml_path)
    assert main([str(sbml_path)]) == 0
    assert (tmp_path / "liver.cellml").is_file()


def test_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path / "missing.xml")])
    assert code == 1
    assert "missing.xml" in capsys.readouterr().err


def test_invalid_model_fails_with_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "body.cellml"
    code = main([str(MODELS_DIR / "glimepiride_body.xml"), "-o", str(out)])
    assert code == 1
    assert "errors" in capsys.readouterr().err
    assert not out.exists()


def test_invalid_model_written_without_validation(tmp_path: Path) -> None:
    out = tmp_path / "body.cellml"
    code = main(
        [str(MODELS_DIR / "glimepiride_body.xml"), "-o", str(out), "--no-validate"]
    )
    assert code == 0
    assert out.is_file()


def test_missing_output_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "missing_dir" / "out.cellml"
    code = main([str(MODELS_DIR / "glimepiride_liver.xml"), "-o", str(out)])
    assert code == 1
    assert "missing_dir" in capsys.readouterr().err
    assert not out.exists()


def test_verbose_logs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "liver.cellml"
    assert main([str(MODELS_DIR / "glimepiride_liver.xml"), "-o", str(out), "-v"]) == 0
    captured = capsys.readouterr()
    assert "variable for species" in captured.out + captured.err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_entry_point_installed(tmp_path: Path) -> None:
    """The console script of the package works."""
    out = tmp_path / "liver.cellml"
    script = shutil.which("sbml2cellml")
    assert script is not None, "sbml2cellml console script not installed, run uv sync"
    result = subprocess.run(
        [script, str(MODELS_DIR / "glimepiride_liver.xml"), "-o", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.is_file()


def test_cellml2sbml_convert_with_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "test_model.xml"
    code = main_cellml2sbml([str(TEST_MODEL_PATH), "-o", str(out)])
    assert code == 0
    assert out.is_file()
    assert str(out) in capsys.readouterr().out


def test_cellml2sbml_default_output_next_to_input(tmp_path: Path) -> None:
    cellml_path = tmp_path / "test_model.cellml"
    shutil.copy(TEST_MODEL_PATH, cellml_path)
    assert main_cellml2sbml([str(cellml_path)]) == 0
    assert (tmp_path / "test_model.xml").is_file()


def test_cellml2sbml_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main_cellml2sbml([str(tmp_path / "missing.cellml")])
    assert code == 1
    assert "missing.cellml" in capsys.readouterr().err


def test_cellml2sbml_invalid_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "invalid.cellml"
    path.write_text(
        '<?xml version="1.0"?><model xmlns="http://www.cellml.org/cellml/2.0#" name="bad">'
        '<component name="c"><variable name="x" units="second"/>'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><apply><eq/><ci>x</ci><ci>y</ci></apply></math>'
        "</component></model>"
    )
    code = main_cellml2sbml([str(path)])
    assert code == 1
    assert "analysed" in capsys.readouterr().err


def test_cellml2sbml_verbose_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "test_model.xml"
    assert main_cellml2sbml([str(TEST_MODEL_PATH), "-o", str(out), "-v"]) == 0
    captured = capsys.readouterr()
    assert "parameter for variable" in captured.out + captured.err


def test_cellml2sbml_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main_cellml2sbml(["--version"])
    assert info.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_cellml2sbml_entry_point_installed(tmp_path: Path) -> None:
    out = tmp_path / "test_model.xml"
    script = shutil.which("cellml2sbml")
    assert script is not None, "cellml2sbml console script not installed, run uv sync"
    result = subprocess.run(
        [script, str(TEST_MODEL_PATH), "-o", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.is_file()


def test_cellml2sbml_missing_output_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "missing_dir" / "out.xml"
    code = main_cellml2sbml([str(TEST_MODEL_PATH), "-o", str(out)])
    assert code == 1
    assert "missing_dir" in capsys.readouterr().err
    assert not out.exists()


def test_cellml2sbml_no_validate_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`main_cellml2sbml` returns 1 on an inconsistent document, but writes
    it and returns 0 with `--no-validate`."""
    path = tmp_path / "test_model.cellml"
    path.write_text(TEST_MODEL_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    real_build_document = cellml2sbml.build_document

    def inconsistent_build_document(
        model: libcellml.Model, analyser_model: Any
    ) -> libsbml.SBMLDocument:
        doc = real_build_document(model, analyser_model)
        rule = doc.getModel().createAssignmentRule()
        rule.setVariable("alpha")
        rule.setMath(libsbml.parseL3Formula("1"))
        return doc

    monkeypatch.setattr(cellml2sbml, "build_document", inconsistent_build_document)

    out = tmp_path / "out.xml"
    assert main_cellml2sbml([str(path), "-o", str(out)]) == 1
    assert not out.exists()
    assert main_cellml2sbml([str(path), "-o", str(out), "--no-validate"]) == 0
    assert out.is_file()
