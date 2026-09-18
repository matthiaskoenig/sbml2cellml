"""The committed BioModels results have the expected shape."""

from pathlib import Path

import pytest

from sbml2cellml.testsuite.results import STAGES, SuiteResult

RESULTS = Path(__file__).parent.parent / "biomodels" / "results.json"


@pytest.mark.skipif(not RESULTS.is_file(), reason="no committed BioModels results")
def test_committed_results() -> None:
    result = SuiteResult.from_json(RESULTS)
    assert result.suite == "biomodels"
    assert result.cases
    for case in result.cases.values():
        assert set(case.stages) == set(STAGES)
        assert case.name
