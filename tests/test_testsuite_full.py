"""The complete SBML test suite, gated on regressions.

Enabled with `SBML2CELLML_TESTSUITE=1` (the linux CI job, `tox -e testsuite`).
Downloads the suite into the cache, runs every runnable case and compares
with the committed `testsuite/results.json`; the rendered report must equal
the committed `docs/testsuite.md`. Improvements are printed: rerun
`sbml2cellml-testsuite run` and commit both files to accept them.
"""

import os
from pathlib import Path

import pytest

from sbml2cellml.testsuite.cases import ensure_suite, load_cases
from sbml2cellml.testsuite.report import TESTSUITE_FIGURE, render_report
from sbml2cellml.testsuite.results import SuiteResult, improvements, regressions
from sbml2cellml.testsuite.runner import run_suite

REPO = Path(__file__).parent.parent
RESULTS = REPO / "testsuite" / "results.json"
REPORT = REPO / "docs" / "testsuite.md"

pytestmark = pytest.mark.testsuite


@pytest.mark.skipif(
    os.environ.get("SBML2CELLML_TESTSUITE") != "1",
    reason="SBML2CELLML_TESTSUITE=1 not set",
)
def test_full_suite_no_regression(tmp_path: Path) -> None:
    committed = SuiteResult.from_json(RESULTS)
    result = run_suite(load_cases(ensure_suite()), tmp_path / "work")
    better = improvements(committed, result)
    if better:
        print(
            "improvements, rerun `sbml2cellml-testsuite run` and commit:\n"
            + "\n".join(better)
        )
    worse = regressions(committed, result)
    assert worse == [], "regressions:\n" + "\n".join(worse)
    assert render_report(result, figure=TESTSUITE_FIGURE) == REPORT.read_text(
        encoding="utf-8"
    ), "docs/testsuite.md is stale, rerun `sbml2cellml-testsuite run`"
