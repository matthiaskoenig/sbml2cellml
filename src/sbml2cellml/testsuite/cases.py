"""The semantic test cases of the SBML test suite.

A case is a directory `NNNNN` with the model in several SBML levels and
versions, `NNNNN-settings.txt` (simulation settings and tolerances),
`NNNNN-results.csv` (expected timecourse) and `NNNNN-model.m` (tags and the
test type). The suite is downloaded from its GitHub release into a cache on
first use.
"""

import logging
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

#: version of the SBML test suite
SUITE_VERSION = "3.5.0"
#: download url of the semantic test cases, formatted with the version
SUITE_URL = (
    "https://github.com/sbmlteam/sbml-test-suite/releases/download/"
    "{version}/semantic_tests_v{version}.zip"
)
#: environment variable overriding the cache root
CACHE_ENV = "SBML2CELLML_CACHE"
#: name of a case directory
CASE_ID = re.compile(r"^\d{5}$")
#: component tags of SBML packages, none of which the converters support
PACKAGE_PREFIXES = (
    "comp",
    "fbc",
    "qual",
    "multi",
    "distrib",
    "spatial",
    "groups",
    "layout",
    "render",
)
#: the only test type the harness runs
TIME_COURSE = "TimeCourse"


class TestSuiteError(RuntimeError):
    """The test suite cannot be obtained or a case cannot be read."""


def cache_dir() -> Path:
    """Root of the cache, `SBML2CELLML_CACHE` or `~/.cache/sbml2cellml`."""
    return Path(os.environ.get(CACHE_ENV, Path.home() / ".cache" / "sbml2cellml"))


def ensure_suite(version: str = SUITE_VERSION, cache: Path | None = None) -> Path:
    """Directory of the semantic cases, downloaded and unpacked on first use.

    Args:
        version: release of the test suite.
        cache: cache root, `cache_dir()` by default.

    Returns:
        The `semantic/` directory with one subdirectory per case.

    Raises:
        TestSuiteError: if the download fails or the archive has not the
            expected layout.
    """
    root = (cache or cache_dir()) / "sbml-test-suite" / version
    semantic = root / "semantic"
    if semantic.is_dir():
        return semantic
    root.mkdir(parents=True, exist_ok=True)
    url = SUITE_URL.format(version=version)
    zip_path = root / f"semantic_tests_v{version}.zip"
    logger.info("Downloading the SBML test suite %s from %s", version, url)
    try:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with zip_path.open("wb") as f_zip:
                for chunk in response.iter_content(1 << 16):
                    f_zip.write(chunk)
    except requests.RequestException as err:
        raise TestSuiteError(f"Download of {url} failed: {err}") from err
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(root)
    if not semantic.is_dir():
        raise TestSuiteError(f"No 'semantic' directory in {zip_path}")
    logger.info("SBML test suite unpacked to %s", semantic)
    return semantic


@dataclass(frozen=True)
class Settings:
    """Simulation settings of a case (`NNNNN-settings.txt`)."""

    start: float
    duration: float
    steps: int
    variables: tuple[str, ...]
    absolute: float
    relative: float
    amount: frozenset[str]
    concentration: frozenset[str]

    @property
    def end(self) -> float:
        """End time of the simulation."""
        return self.start + self.duration


def _key_values(text: str) -> dict[str, str]:
    """`key: value` lines of a settings or model file."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def _split(value: str) -> tuple[str, ...]:
    """Comma separated list, empty for an empty value."""
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_settings(text: str) -> Settings:
    """Parse a settings file.

    Args:
        text: content of `NNNNN-settings.txt`.

    Returns:
        The settings.

    Raises:
        TestSuiteError: if `start`, `duration` or `steps` is missing.
    """
    values = _key_values(text)
    for key in ("start", "duration", "steps"):
        if key not in values:
            raise TestSuiteError(f"Settings without '{key}'.")
    return Settings(
        start=float(values["start"]),
        duration=float(values["duration"]),
        steps=int(values["steps"]),
        variables=_split(values.get("variables", "")),
        absolute=float(values.get("absolute", "0")),
        relative=float(values.get("relative", "0")),
        amount=frozenset(_split(values.get("amount", ""))),
        concentration=frozenset(_split(values.get("concentration", ""))),
    )


def parse_model_info(text: str) -> dict[str, list[str]]:
    """Parse the `key: values` lines of a `NNNNN-model.m` file.

    Args:
        text: content of the file.

    Returns:
        The values per key, e.g. `testTags`, `componentTags`, `testType`.
    """
    return {key: list(_split(value)) for key, value in _key_values(text).items()}


@dataclass(frozen=True)
class Case:
    """One semantic test case."""

    id: str
    case_dir: Path
    sbml_path: Path | None
    settings: Settings
    expected: pd.DataFrame
    test_tags: tuple[str, ...]
    component_tags: tuple[str, ...]
    test_type: str

    @property
    def packages(self) -> tuple[str, ...]:
        """SBML packages the case uses, from the component tags."""
        return tuple(
            sorted({tag.split(":")[0] for tag in self.component_tags if ":" in tag})
        )


def load_case(case_dir: Path) -> Case:
    """Read a case directory.

    Args:
        case_dir: directory `NNNNN`.

    Returns:
        The case; `sbml_path` is `None` when there is no L3V2 file.

    Raises:
        TestSuiteError: if the settings, results or model file is missing.
    """
    cid = case_dir.name
    for suffix in ("settings.txt", "results.csv", "model.m"):
        if not (case_dir / f"{cid}-{suffix}").is_file():
            raise TestSuiteError(f"Case {cid} has no {suffix}.")
    sbml_path: Path | None = case_dir / f"{cid}-sbml-l3v2.xml"
    if sbml_path is not None and not sbml_path.is_file():
        sbml_path = None
    info = parse_model_info((case_dir / f"{cid}-model.m").read_text(encoding="utf-8"))
    return Case(
        id=cid,
        case_dir=case_dir,
        sbml_path=sbml_path,
        settings=parse_settings(
            (case_dir / f"{cid}-settings.txt").read_text(encoding="utf-8")
        ),
        expected=pd.read_csv(case_dir / f"{cid}-results.csv"),
        test_tags=tuple(info.get("testTags", [])),
        component_tags=tuple(info.get("componentTags", [])),
        test_type=(info.get("testType") or [""])[0],
    )


def skip_reason(case: Case) -> str | None:
    """Why a case is not run, `None` if it is runnable."""
    if case.sbml_path is None:
        return "no L3V2 file"
    if case.test_type != TIME_COURSE:
        return f"test type {case.test_type}"
    for package in case.packages:
        if package in PACKAGE_PREFIXES:
            return f"package {package}"
    return None


def load_cases(root: Path, ids: list[str] | None = None) -> list[Case]:
    """Read the cases of a suite directory.

    Args:
        root: the `semantic/` directory.
        ids: case ids to read, all when `None`.

    Returns:
        The cases sorted by id.
    """
    wanted = set(ids) if ids is not None else None
    cases: list[Case] = []
    for case_dir in sorted(root.iterdir()):
        if not case_dir.is_dir() or not CASE_ID.match(case_dir.name):
            continue
        if wanted is not None and case_dir.name not in wanted:
            continue
        cases.append(load_case(case_dir))
    return cases
