"""Runner producing a `SuiteResult` from a BioModels selection.

The pipeline itself (`sbml2cellml.testsuite.runner.run_suite`) is reused
unchanged; this module only turns a list of model ids into runnable cases,
skipping the ids whose info or download request fails, whose case cannot be
built or whose model has no variable (`prepare_cases`), and runs them
(`run_biomodels`).
"""

import logging
from collections.abc import Callable
from pathlib import Path

from sbml2cellml.biomodels.cases import biomodel_case
from sbml2cellml.biomodels.models import download_model, model_info, packages
from sbml2cellml.testsuite.cases import Case
from sbml2cellml.testsuite.results import SuiteResult
from sbml2cellml.testsuite.runner import run_suite

logger = logging.getLogger(__name__)

#: name of the suite in the produced `SuiteResult`
SUITE = "biomodels"


def prepare_cases(
    ids: list[str], cache: Path | None = None
) -> tuple[list[Case], dict[str, str]]:
    """Build the runnable cases of a list of BioModels ids.

    Args:
        ids: BioModels ids, e.g. `BIOMD0000000001`.
        cache: cache root, `sbml2cellml.testsuite.cases.cache_dir()` by
            default.

    Returns:
        The cases built and a skip reason per id whose info or download
        request failed (`download failed: <ExceptionType>`), whose case
        could not be built (`case failed: <ExceptionType>`) or whose model
        has no variable (`no variables`); a case with SBML packages is still
        returned, `sbml2cellml.testsuite.cases.skip_reason` skips it later.
    """
    cases: list[Case] = []
    skipped: dict[str, str] = {}
    for model_id in ids:
        try:
            info = model_info(model_id, cache)
            path = download_model(model_id, cache)
        except Exception as err:
            logger.warning("%s skipped: %s", model_id, err)
            skipped[model_id] = f"download failed: {type(err).__name__}"
            continue
        try:
            case = biomodel_case(info, path, packages(path))
        except Exception as err:
            logger.warning("%s skipped: %s", model_id, err)
            skipped[model_id] = f"case failed: {type(err).__name__}"
            continue
        if not case.settings.variables:
            logger.warning("%s skipped: no variables", model_id)
            skipped[model_id] = "no variables"
            continue
        cases.append(case)
    return cases, skipped


def run_biomodels(
    ids: list[str],
    cache: Path | None = None,
    work_dir: Path = Path("biomodels/work"),
    timeout: float = 60.0,
    progress: Callable[[str], None] | None = None,
) -> SuiteResult:
    """Run the pipeline for a list of BioModels ids.

    Args:
        ids: BioModels ids to run.
        cache: cache root, `sbml2cellml.testsuite.cases.cache_dir()` by
            default.
        work_dir: directory for the converted files, created if needed.
        timeout: seconds per simulator call.
        progress: called with the finished status line of the case after
            every runnable case, see `sbml2cellml.testsuite.runner.run_suite`.

    Returns:
        The suite result, `suite="biomodels"`.
    """
    cases, skipped = prepare_cases(ids, cache)
    result = run_suite(cases, work_dir, timeout=timeout, progress=progress)
    result.suite = SUITE
    result.skipped.update(skipped)
    return result
