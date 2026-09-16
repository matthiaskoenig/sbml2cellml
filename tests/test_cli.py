"""Tests of the command line interface."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sbml2cellml.cli import main
from tests.conftest import MODELS_DIR


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
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sbml2cellml.cli",
            str(MODELS_DIR / "glimepiride_liver.xml"),
            "-o",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.is_file()
