"""Tests of the suite results and the regression detection."""

import json
from pathlib import Path

from sbml2cellml.testsuite.results import (
    STAGES,
    CaseResult,
    StageResult,
    SuiteResult,
    improvements,
    regressions,
)


def suite(status_00001: str, message: str = "") -> SuiteResult:
    stages = {stage: StageResult("pass") for stage in STAGES}
    stages["roundtrip"] = StageResult(
        status_00001, message, 0.5 if status_00001 == "fail" else None
    )
    return SuiteResult(
        suite="3.5.0",
        version="0.1.0",
        cases={
            "00001": CaseResult(
                "00001", ["Amount"], ["Compartment", "Species"], stages
            ),
            "00002": CaseResult(
                "00002", [], [], {stage: StageResult("skip", "x") for stage in STAGES}
            ),
        },
        skipped={"00003": "package comp"},
    )


def test_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    original = suite("fail", "S1 exceeds the tolerance")
    original.cases["00001"].name = "Repressilator"
    original.to_json(path)
    text = path.read_text()
    assert text.startswith("{")
    assert '"00001"' in text and "timestamp" not in text
    loaded = SuiteResult.from_json(path)
    assert loaded == original
    assert loaded.cases["00001"].name == "Repressilator"
    original.to_json(path)
    assert path.read_text() == text  # deterministic


def test_from_json_without_name(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    original = suite("pass")
    original.to_json(path)
    data = json.loads(path.read_text())
    for case in data["cases"].values():
        case.pop("name", None)
    path.write_text(json.dumps(data))
    loaded = SuiteResult.from_json(path)
    assert loaded.cases["00001"].name == ""


def test_json_rounds_max_excess(tmp_path: Path) -> None:
    # a full-precision max_excess is an artifact of the solver and the
    # machine it ran on; rounding to 3 significant digits keeps the file
    # stable across machines instead of churning on every regeneration
    path = tmp_path / "results.json"
    original = suite("fail", "S1 exceeds the tolerance")
    original.cases["00001"].stages["roundtrip"].max_excess = 0.5
    original.to_json(path)
    loaded = SuiteResult.from_json(path)
    assert loaded.cases["00001"].stages["roundtrip"].max_excess == 0.5

    original.cases["00001"].stages["roundtrip"].max_excess = 0.009634334135793121
    original.to_json(path)
    loaded = SuiteResult.from_json(path)
    assert loaded.cases["00001"].stages["roundtrip"].max_excess == 0.00963


def test_counts() -> None:
    result = suite("fail")
    assert result.counts("roundtrip") == {"pass": 0, "fail": 1, "skip": 1}
    assert result.counts("roadrunner") == {"pass": 1, "fail": 0, "skip": 1}


def test_regressions_and_improvements() -> None:
    old = suite("pass")
    new = suite("fail", "S1 exceeds the tolerance")
    assert regressions(old, new) == [
        "00001 roundtrip: pass -> fail (S1 exceeds the tolerance)"
    ]
    assert regressions(new, old) == []
    assert improvements(new, old) == ["00001 roundtrip: fail -> pass"]
    missing = suite("pass")
    del missing.cases["00002"]
    assert regressions(old, missing) == ["00002: missing"]
