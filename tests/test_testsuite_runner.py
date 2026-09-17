"""Tests of the pipeline on the fixture cases."""

import dataclasses
from pathlib import Path

import libsbml

from sbml2cellml import __version__
from sbml2cellml.testsuite.cases import SUITE_VERSION, load_cases
from sbml2cellml.testsuite.results import STAGES, STATUSES, SuiteResult
from sbml2cellml.testsuite.runner import reference_selections, run_suite

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"


def test_reference_selections() -> None:
    case = load_cases(FIXTURES, ids=["00001"])[0]
    model = libsbml.readSBMLFromFile(str(case.sbml_path)).getModel()
    # 00001 expects amounts
    assert reference_selections(case, model) == ["S1", "S2"]
    concentration = dataclasses.replace(
        case.settings, amount=frozenset(), concentration=frozenset({"S1", "S2"})
    )
    case_c = dataclasses.replace(case, settings=concentration)
    assert reference_selections(case_c, model) == ["[S1]", "[S2]"]


def test_run_suite_on_fixtures(tmp_path: Path) -> None:
    cases = load_cases(FIXTURES)
    seen: list[str] = []
    result = run_suite(cases, tmp_path, timeout=60.0, progress=seen.append)
    assert result.suite == SUITE_VERSION
    assert result.version == __version__
    assert set(result.cases) == {c.id for c in cases}
    assert result.skipped == {}
    assert len(seen) == len(cases)
    for case in result.cases.values():
        assert set(case.stages) == set(STAGES)
        for stage in case.stages.values():
            assert stage.status in STATUSES
    first = result.cases["00001"].stages
    assert first["reference"].status == "pass", first["reference"].message
    assert first["sbml2cellml"].status == "pass", first["sbml2cellml"].message
    assert (tmp_path / "00001.cellml").is_file()
    # a stage after a failed conversion is skipped, never run
    for case in result.cases.values():
        if case.stages["sbml2cellml"].status == "fail":
            assert case.stages["libopencor"].status == "skip"
            assert case.stages["cellml2sbml"].status == "skip"
            assert case.stages["roundtrip"].status == "skip"
    path = tmp_path / "results.json"
    result.to_json(path)
    assert SuiteResult.from_json(path) == result


def test_run_suite_skips_unrunnable(tmp_path: Path) -> None:
    import shutil

    root = tmp_path / "semantic"
    shutil.copytree(FIXTURES / "00001", root / "00001")
    (root / "00001" / "00001-sbml-l3v2.xml").unlink()
    result = run_suite(load_cases(root), tmp_path / "work")
    assert result.cases == {}
    assert result.skipped == {"00001": "no L3V2 file"}
