"""The semantic test cases of the SBML test suite.

A case is a directory `NNNNN` with the model in several SBML levels and
versions, `NNNNN-settings.txt` (simulation settings and tolerances),
`NNNNN-results.csv` (expected timecourse) and `NNNNN-model.m` (tags and the
test type). The cases are fetched from a pinned commit of the repository of
the suite into a cache on first use: the fixes of the cases arrive in the
repository long before they are released, so `SUITE_COMMIT` and not a
release is what the harness runs.
"""

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

#: commit of the suite the harness runs; bump it to take in new cases and
#: fixed expected results, then regenerate the committed results
SUITE_COMMIT = "bbcbc80c4daec79fea301299f981746408a1742b"
#: label of the suite in the results and the report
SUITE_VERSION = SUITE_COMMIT[:7]
#: repository of the SBML test suite
SUITE_REPOSITORY = "https://github.com/sbmlteam/sbml-test-suite.git"
#: path of the semantic cases inside the repository
SUITE_CASES = "cases/semantic"
#: seconds the git commands of the download may take
SUITE_TIMEOUT = 600.0
#: environment variable overriding the cache root
CACHE_ENV = "SBML2CELLML_CACHE"
#: name of a case directory
CASE_ID = re.compile(r"^\d{5}$")
#: component tags of SBML packages, none of which the converters support;
#: `layout` and `render` are deliberately absent - they only describe the
#: diagram of the model, not its math, so a model using them still runs
PACKAGE_PREFIXES = (
    "comp",
    "fbc",
    "qual",
    "multi",
    "distrib",
    "spatial",
    "groups",
)
#: the only test type the harness runs
TIME_COURSE = "TimeCourse"


class TestSuiteError(RuntimeError):
    """The test suite cannot be obtained or a case cannot be read."""

    __test__ = False  # the name starts with Test, pytest must not collect it


def cache_dir() -> Path:
    """Root of the cache, `SBML2CELLML_CACHE` or `~/.cache/sbml2cellml`."""
    return Path(os.environ.get(CACHE_ENV, Path.home() / ".cache" / "sbml2cellml"))


def _git(arguments: list[str], cwd: Path) -> None:
    """Run a git command in a directory.

    Args:
        arguments: the arguments after `git`.
        cwd: working directory of the command.

    Raises:
        TestSuiteError: if git is missing, times out or fails; the message
            carries the output of the command.
    """
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=SUITE_TIMEOUT,
        )
    except FileNotFoundError as err:
        raise TestSuiteError(
            "git is needed to fetch the cases of the SBML test suite"
        ) from err
    except subprocess.TimeoutExpired as err:
        raise TestSuiteError(f"git {' '.join(arguments)} timed out") from err
    if completed.returncode != 0:
        raise TestSuiteError(
            f"git {' '.join(arguments)} failed:\n{completed.stdout}{completed.stderr}"
        )


def ensure_suite(commit: str = SUITE_COMMIT, cache: Path | None = None) -> Path:
    """Directory of the semantic cases, fetched on first use.

    The cases are the only part of the repository which is fetched: a
    partial clone without blobs, one commit deep, with `cases/semantic`
    checked out (about 80 MB of the 400 MB of the repository).

    Args:
        commit: commit of the suite to fetch.
        cache: cache root, `cache_dir()` by default.

    Returns:
        The directory with one subdirectory per case.

    Raises:
        TestSuiteError: if git is missing or the fetch fails, or if the
            commit has no `cases/semantic` directory.
    """
    root = (cache or cache_dir()) / "sbml-test-suite" / commit[:7]
    semantic = root / "semantic"
    if semantic.is_dir():
        return semantic
    root.mkdir(parents=True, exist_ok=True)
    # the cases are checked out into a scratch directory next to the target
    # and renamed into place only once the checkout is complete, so a
    # process killed in the middle never leaves a half `semantic/` that a
    # later call returns
    clone = root / "clone"
    if clone.is_dir():
        shutil.rmtree(clone)
    clone.mkdir()
    logger.info("Fetching %s of the SBML test suite %s", SUITE_CASES, commit[:7])
    try:
        _git(["init", "--quiet", "."], clone)
        _git(["remote", "add", "origin", SUITE_REPOSITORY], clone)
        # a partial clone needs the extension on the repository it lazily
        # fetches the missing objects from
        _git(["config", "extensions.partialClone", "origin"], clone)
        _git(["sparse-checkout", "set", "--cone", SUITE_CASES], clone)
        _git(
            [
                "fetch",
                "--quiet",
                "--depth",
                "1",
                "--filter=blob:none",
                "origin",
                commit,
            ],
            clone,
        )
        _git(["checkout", "--quiet", "FETCH_HEAD"], clone)
        cases = clone / SUITE_CASES
        if not cases.is_dir():
            raise TestSuiteError(f"Commit {commit} has no '{SUITE_CASES}' directory")
        os.replace(cases, semantic)
    except BaseException:
        shutil.rmtree(clone, ignore_errors=True)
        raise
    shutil.rmtree(clone, ignore_errors=True)
    logger.info("SBML test suite %s unpacked to %s", commit[:7], semantic)
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

    Cases of a test type other than `TimeCourse` (e.g. `FluxBalanceSteadyState`)
    leave `start`, `duration` and `steps` empty; they parse to `0` and are never
    used because `skip_reason` filters them out before a run.

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
        start=float(values["start"] or "0"),
        duration=float(values["duration"] or "0"),
        steps=int(values["steps"] or "0"),
        variables=_split(values.get("variables", "")),
        absolute=float(values.get("absolute", "0")),
        relative=float(values.get("relative", "0")),
        amount=frozenset(_split(values.get("amount", ""))),
        concentration=frozenset(_split(values.get("concentration", ""))),
    )


def parse_model_info(text: str) -> dict[str, list[str]]:
    """Parse the `key: values` lines of a `NNNNN-model.m` file.

    A model file opens with a comment marker on its own line, a blank line,
    the header block of `key: value` pairs, a blank line and then the prose
    description (a few files carry an extra "Previous version of this
    file:" comment line before the marker, or wrap a value like `synopsis`
    onto its own blank-line-separated continuation). Only the header block
    is parsed: the paragraphs (blocks separated by a blank line) up to and
    including the first genuine `key: value` paragraph, plus at most one
    further blank-line gap, so a wrapped value does not cut the header
    short but prose describing the model later in the file (typically
    several paragraphs further, e.g. a "Note:" line) is not mistaken for
    more of it.

    Args:
        text: content of the file.

    Returns:
        The values per key, e.g. `testTags`, `componentTags`, `testType`.
    """
    info: dict[str, str] = {}
    started = False
    gap = 0
    for block in re.split(r"\n[ \t]*\n", text):
        # a header key is a single identifier (e.g. "testType"); a stray
        # "Previous version of this file:" comment line has spaces in its
        # key and is dropped rather than mistaken for a header field
        values = {k: v for k, v in _key_values(block).items() if k.isidentifier()}
        if values:
            info.update(values)
            started = True
            gap = 0
        elif started:
            gap += 1
            if gap > 1:
                break
    return {key: list(_split(value)) for key, value in info.items()}


@dataclass(frozen=True)
class Case:
    """One semantic test case.

    `expected` is `None` for a case without expected results (e.g. a model
    from a model repository): the sbmlsim-core simulation of the original model
    becomes the expected results for the later stages. `name` is a display name (e.g. the model
    name), empty for the SBML test suite cases.
    """

    id: str
    case_dir: Path
    sbml_path: Path | None
    settings: Settings
    expected: pd.DataFrame | None
    test_tags: tuple[str, ...]
    component_tags: tuple[str, ...]
    test_type: str
    name: str = ""

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
    expected = pd.read_csv(case_dir / f"{cid}-results.csv")
    # the first column is always the variable of integration, named "time"
    # in most cases but "Time" (or another case) in many of them; renamed
    # only when no other column is already "time" so it does not collide
    # with a variable of that name (e.g. 01820/01821, which declare a
    # variable "time"/"Time"/"TIME" among their settings variables); those
    # two cases fail with "duplicate column names" regardless, from
    # the selection labels of the simulator colliding, not from this rename
    if "time" not in expected.columns[1:]:
        expected = expected.rename(columns={expected.columns[0]: "time"})
    return Case(
        id=cid,
        case_dir=case_dir,
        sbml_path=sbml_path,
        settings=parse_settings(
            (case_dir / f"{cid}-settings.txt").read_text(encoding="utf-8")
        ),
        expected=expected,
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
