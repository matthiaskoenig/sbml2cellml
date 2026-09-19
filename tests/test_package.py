"""Tests of the package metadata and the test fixtures."""

import importlib.metadata
import logging
import re
from pathlib import Path

import sbml2cellml
from sbml2cellml import log
from tests.conftest import GLIMEPIRIDE_MODELS, MODELS_DIR, TEST_MODEL_PATH

ROOT = Path(__file__).parent.parent


def test_version_is_consistent() -> None:
    """The module, the installed metadata and the citation agree on the version.

    `bump-my-version` updates the module and `CITATION.cff`; the metadata of the
    editable install follows through the `cache-keys` of `[tool.uv]`.
    """
    version = sbml2cellml.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert importlib.metadata.version("sbml2cellml") == version
    assert f'version: "{version}"' in (ROOT / "CITATION.cff").read_text()


def test_release_notes_are_in_the_documentation() -> None:
    """Every release has its notes, in the navigation and in the overview.

    The notes of the current version exist before it is bumped, so a release
    cannot be made without them.
    """
    notes_dir = ROOT / "docs" / "release-notes"
    versions = {path.stem for path in notes_dir.glob("*.md")} - {"index"}
    assert sbml2cellml.__version__ in versions
    nav = (ROOT / "zensical.toml").read_text()
    overview = (notes_dir / "index.md").read_text()
    for version in versions:
        assert f'{{ "{version}" = "release-notes/{version}.md" }}' in nav, version
        assert f"| [{version}]({version}.md) |" in overview, version


def test_models_exist() -> None:
    assert TEST_MODEL_PATH.is_file()
    for name in GLIMEPIRIDE_MODELS:
        assert (MODELS_DIR / f"{name}.xml").is_file(), name


def test_package_logger_has_null_handler() -> None:
    handlers = logging.getLogger("sbml2cellml").handlers
    assert any(isinstance(h, logging.NullHandler) for h in handlers)


def test_enable_rich_logging_is_idempotent() -> None:
    logger = log.enable_rich_logging()
    log.enable_rich_logging()
    rich_handlers = [h for h in logger.handlers if type(h).__name__ == "RichHandler"]
    assert len(rich_handlers) == 1
