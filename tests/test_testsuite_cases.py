"""Tests of the test suite cases: fetch, cache, parsing."""

import shutil
from pathlib import Path

import pytest

from sbml2cellml.testsuite import cases
from sbml2cellml.testsuite.cases import (
    Settings,
    TestSuiteError,
    ensure_suite,
    load_case,
    load_cases,
    parse_model_info,
    parse_settings,
    skip_reason,
)

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"
EVENT_CASE = "00026"
FUNCTION_CASE = "00025"


def test_parse_settings() -> None:
    settings = parse_settings((FIXTURES / "00001" / "00001-settings.txt").read_text())
    assert settings == Settings(
        start=0.0,
        duration=5.0,
        steps=50,
        variables=("S1", "S2"),
        absolute=1e-7,
        relative=1e-4,
        amount=frozenset({"S1", "S2"}),
        concentration=frozenset(),
    )
    assert settings.end == 5.0


def test_parse_settings_missing_key_raises() -> None:
    with pytest.raises(TestSuiteError, match="duration"):
        parse_settings("start: 0\nsteps: 10\nvariables: S1\n")


def test_parse_model_info() -> None:
    info = parse_model_info((FIXTURES / "00001" / "00001-model.m").read_text())
    assert info["testType"] == ["TimeCourse"]
    assert "Amount" in info["testTags"]
    assert "Compartment" in info["componentTags"]
    # the fixture's prose contains a "Note:" line after a blank line, which
    # must not be parsed as a key
    assert "Note" not in info


def test_parse_model_info_ignores_prose_after_header() -> None:
    text = (
        "(*\n"
        "\n"
        "category:      Test\n"
        "testType:      TimeCourse\n"
        "\n"
        "This model does something.\n"
        "\n"
        "It has more than one paragraph of prose.\n"
        "\n"
        "Note: something that looks like a key but is prose.\n"
        "\n"
        "*)\n"
    )
    info = parse_model_info(text)
    assert info == {"category": ["Test"], "testType": ["TimeCourse"]}
    assert "Note" not in info


def test_parse_model_info_tolerates_wrapped_header_value() -> None:
    # a synopsis wrapped onto its own blank-line-separated continuation
    # (as seen in some real cases) must not cut the header short
    text = (
        "(*\n"
        "\n"
        "category:      Test\n"
        "\n"
        "synopsis:      A model\n"
        "\n"
        "               with a wrapped synopsis.\n"
        "\n"
        "componentTags: Compartment\n"
        "\n"
        "testTags:      Amount\n"
        "\n"
        "testType:      TimeCourse\n"
        "\n"
        "\n"
        "\n"
        "Note: earlier versions of this test were different.\n"
        "\n"
        "*)\n"
    )
    info = parse_model_info(text)
    assert info["testType"] == ["TimeCourse"]
    assert info["componentTags"] == ["Compartment"]
    assert info["testTags"] == ["Amount"]


def test_load_case() -> None:
    case = load_case(FIXTURES / "00001")
    assert case.id == "00001"
    assert case.sbml_path == FIXTURES / "00001" / "00001-sbml-l3v2.xml"
    assert case.test_type == "TimeCourse"
    assert case.expected is not None
    assert list(case.expected.columns) == ["time", "S1", "S2"]
    assert len(case.expected) == 51
    assert skip_reason(case) is None


def test_load_case_keeps_the_name_of_the_time_column(tmp_path: Path) -> None:
    """The comparison takes the time points of a case by their position.

    The first column of the expected results is the variable of
    integration, called `Time` in many cases and `time` in the others, and
    a model may name a variable of its own `time` (01820, 01821), so the
    column keeps the name the case gives it.
    """
    case_dir = tmp_path / "10006"
    shutil.copytree(FIXTURES / "00001", case_dir)
    for f in list(case_dir.iterdir()):
        f.rename(case_dir / f.name.replace("00001", "10006"))
    results = case_dir / "10006-results.csv"
    text = results.read_text()
    assert text.startswith("time,")
    results.write_text("Time," + text.split(",", 1)[1])
    case = load_case(case_dir)
    assert case.expected is not None
    assert list(case.expected.columns) == ["Time", "S1", "S2"]


def test_load_cases_sorted_and_filtered() -> None:
    all_cases = load_cases(FIXTURES)
    assert [c.id for c in all_cases] == sorted(["00001", EVENT_CASE, FUNCTION_CASE])
    assert [c.id for c in load_cases(FIXTURES, ids=[EVENT_CASE])] == [EVENT_CASE]
    assert (
        "EventNoDelay"
        in next(c for c in all_cases if c.id == EVENT_CASE).component_tags
    )
    assert (
        "FunctionDefinition"
        in next(c for c in all_cases if c.id == FUNCTION_CASE).component_tags
    )


def test_skip_reasons(tmp_path: Path) -> None:

    src = FIXTURES / "00001"
    # no L3V2 file
    no_l3v2 = tmp_path / "10001"
    shutil.copytree(src, no_l3v2)
    for f in no_l3v2.iterdir():
        f.rename(no_l3v2 / f.name.replace("00001", "10001"))
    (no_l3v2 / "10001-sbml-l3v2.xml").unlink()
    assert skip_reason(load_case(no_l3v2)) == "no L3V2 file"
    # the fbc package, which no converter supports
    fbc = tmp_path / "10002"
    shutil.copytree(src, fbc)
    for f in fbc.iterdir():
        f.rename(fbc / f.name.replace("00001", "10002"))
    m = fbc / "10002-model.m"
    m.write_text(
        m.read_text().replace("componentTags: ", "componentTags: fbc:Objective, ")
    )
    assert skip_reason(load_case(fbc)) == "package fbc"
    # the comp package runs, its submodels are flattened
    comp = tmp_path / "10003"
    shutil.copytree(src, comp)
    for f in comp.iterdir():
        f.rename(comp / f.name.replace("00001", "10003"))
    m = comp / "10003-model.m"
    m.write_text(
        m.read_text().replace("componentTags: ", "componentTags: comp:Submodel, ")
    )
    assert skip_reason(load_case(comp)) is None
    # other test type
    other = tmp_path / "10004"
    shutil.copytree(src, other)
    for f in other.iterdir():
        f.rename(other / f.name.replace("00001", "10004"))
    m = other / "10004-model.m"
    m.write_text(
        m.read_text().replace("testType:      TimeCourse", "testType: SteadyState")
    )
    assert skip_reason(load_case(other)) == "test type SteadyState"


def test_ensure_suite_fetches_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_git(arguments: list[str], cwd: Path) -> None:
        calls.append(arguments)
        if arguments[0] == "checkout":
            # the sparse checkout of the cases of the commit
            target = cwd / cases.SUITE_CASES / "00001"
            target.mkdir(parents=True)
            for f in (FIXTURES / "00001").iterdir():
                shutil.copy(f, target / f.name)

    monkeypatch.setattr(cases, "_git", fake_git)
    monkeypatch.setenv(cases.CACHE_ENV, str(tmp_path))
    semantic = ensure_suite()
    assert semantic == tmp_path / "sbml-test-suite" / cases.SUITE_VERSION / "semantic"
    assert (semantic / "00001" / "00001-settings.txt").is_file()
    assert ["checkout", "--quiet", "FETCH_HEAD"] in calls
    assert any(
        cases.SUITE_COMMIT in arguments and arguments[0] == "fetch"
        for arguments in calls
    )
    assert not (semantic.parent / "clone").exists()
    fetches = len(calls)
    ensure_suite()
    assert len(calls) == fetches


def test_ensure_suite_failed_fetch_raises_and_leaves_no_semantic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_git(arguments: list[str], cwd: Path) -> None:
        if arguments[0] == "fetch":
            raise TestSuiteError("git fetch failed")

    monkeypatch.setattr(cases, "_git", fake_git)
    monkeypatch.setenv(cases.CACHE_ENV, str(tmp_path))
    with pytest.raises(TestSuiteError):
        ensure_suite()
    root = tmp_path / "sbml-test-suite" / cases.SUITE_VERSION
    assert not (root / "semantic").exists()
    assert not (root / "clone").exists()


def test_ensure_suite_without_cases_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a commit whose checkout has no cases/semantic directory
    monkeypatch.setattr(cases, "_git", lambda arguments, cwd: None)
    monkeypatch.setenv(cases.CACHE_ENV, str(tmp_path))
    with pytest.raises(TestSuiteError, match=cases.SUITE_CASES):
        ensure_suite()
    assert not (tmp_path / "sbml-test-suite" / cases.SUITE_VERSION / "clone").exists()


def test_git_reports_a_failed_command(tmp_path: Path) -> None:
    with pytest.raises(TestSuiteError, match="rev-parse"):
        cases._git(["rev-parse", "--verify", "nothing-here"], tmp_path)
