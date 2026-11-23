"""The pipeline of the Physiome check, which starts from the CellML model.

The five stages mirror the ones of the test suite, in the order of the
conversion of a CellML model (`sbml2cellml.testsuite.results.CELLML_STAGES`):

1. `libopencor` simulates the model of the repository; its result is what
   the later stages are compared with, since the repository has no expected
   results.
2. `cellml2sbml` converts the model to SBML.
3. `sbmlsim` simulates the SBML model and compares it.
4. `sbml2cellml` converts the SBML model back to CellML.
5. `roundtrip` simulates that model with libopencor and compares it.

The CellML simulation names a variable by its name, or by `component/name`
when more than one variable of the model has that name, and the SBML
simulation by the id of its equivalence set; `PhysiomeCase.columns` maps the
first to the second, so that every comparison runs on the same columns.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from sbml2cellml import __version__, convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.physiome.cases import PhysiomeCase, physiome_case
from sbml2cellml.physiome.models import Exposure, model_path
from sbml2cellml.testsuite.compare import compare, is_informative, requested_frame
from sbml2cellml.testsuite.results import (
    CELLML_STAGES,
    CaseResult,
    StageResult,
    SuiteResult,
)
from sbml2cellml.testsuite.runner import error_message, simulate_stage, stage_result
from sbml2cellml.testsuite.worker import SimulatorWorker, frame

logger = logging.getLogger(__name__)

#: name of the check in the results file
SUITE_NAME = "physiome"


#: the reason of a skipped model by a phrase of the error which causes it;
#: the report groups the skipped models by their reason, so the reason is
#: the kind of the problem and the complete error goes to the log
SKIP_REASONS: tuple[tuple[str, str], ...] = (
    ("cannot be analysed", "model cannot be analysed"),
    ("could not be parsed", "model cannot be parsed"),
    ("Imports of CellML model", "imports cannot be resolved"),
    ("has no variables", "model has no variables"),
    ("has no file", "file missing in the workspace"),
    ("git ", "workspace cannot be cloned"),
)


def skip_reason(err: BaseException) -> str:
    """The reason a model is skipped, the kind of the problem.

    Args:
        err: the error of the clone or of the construction of the case.

    Returns:
        The reason of `SKIP_REASONS` whose phrase the error holds, else the
        first line of the message.
    """
    message = error_message(err)
    for phrase, reason in SKIP_REASONS:
        if phrase in message:
            return reason
    return message.splitlines()[0]


def prepare_cases(
    exposures: list[Exposure], cache: Path | None = None
) -> tuple[list[PhysiomeCase], dict[str, str]]:
    """Clone the workspaces of the exposures and build their cases.

    A model which cannot be cloned, read or analysed is skipped with the
    kind of its problem (`skip_reason`), its complete error is logged.

    Args:
        exposures: the exposures of the selection.
        cache: cache root of the workspaces.

    Returns:
        The cases and the skipped exposures with the reason, by id.
    """
    cases: list[PhysiomeCase] = []
    skipped: dict[str, str] = {}
    for exposure in exposures:
        try:
            cases.append(physiome_case(exposure, model_path(exposure, cache)))
        except Exception as err:
            skipped[exposure.id] = skip_reason(err)
            logger.warning("%s skipped: %s", exposure.id, error_message(err))
    return cases, skipped


def _expected(df: pd.DataFrame, case: PhysiomeCase) -> pd.DataFrame:
    """The result of the CellML simulation with the SBML ids as columns."""
    renamed = df.rename(columns=case.columns)
    renamed = renamed.loc[:, ~renamed.columns.duplicated()]
    return requested_frame(renamed, {}, case.case.settings)


def run_case(
    case: PhysiomeCase,
    work_dir: Path,
    sbmlsim: SimulatorWorker,
    libopencor: SimulatorWorker,
) -> CaseResult:
    """Run the five stages of a case of the repository.

    Args:
        case: the case with the CellML model.
        work_dir: directory for the converted files.
        sbmlsim: worker for the SBML simulation.
        libopencor: worker for the CellML simulations.

    Returns:
        The stage results; a stage whose input stage failed is `skip`. The
        libopencor simulation of the model gives the expected results, so
        every later stage is skipped when it fails.
    """
    settings = case.case.settings
    stages: dict[str, StageResult] = {}

    def _result(informative: bool | None = None) -> CaseResult:
        return CaseResult(
            case.case.id,
            list(case.case.test_tags),
            list(case.case.component_tags),
            stages,
            name=case.case.name,
            informative=informative,
        )

    # libopencor: the model of the repository gives the expected results
    expected: pd.DataFrame | None = None
    try:
        result = simulate_stage(
            libopencor,
            "simulate_cellml",
            cellml_path=str(case.cellml_path),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
        )
        expected = _expected(frame(result), case)
        stages["libopencor"] = StageResult(
            "pass",
            seconds=result["seconds"],
            setup_seconds=result["setup_seconds"],
        )
    except Exception as err:
        stages["libopencor"] = StageResult("fail", error_message(err))
        for stage in ("cellml2sbml", "sbmlsim", "sbml2cellml", "roundtrip"):
            stages[stage] = StageResult("skip", "libopencor failed")
        return _result()

    informative = is_informative(expected, settings)

    # cellml2sbml
    sbml_path = work_dir / f"{case.case.id}.xml"
    try:
        convert_cellml2sbml(case.cellml_path, sbml_path=sbml_path, validate=True)
        stages["cellml2sbml"] = StageResult("pass")
    except Exception as err:
        stages["cellml2sbml"] = StageResult("fail", error_message(err))
        for stage in ("sbmlsim", "sbml2cellml", "roundtrip"):
            stages[stage] = StageResult("skip", "cellml2sbml failed")
        return _result(informative)

    # sbmlsim
    try:
        result = simulate_stage(
            sbmlsim,
            "simulate_sbml",
            sbml=sbml_path.read_text(encoding="utf-8"),
            selections=list(settings.variables),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
            base_path=str(sbml_path.parent),
        )
        df = requested_frame(frame(result), {}, settings)
        stages["sbmlsim"] = stage_result(compare(df, expected, settings), result)
    except Exception as err:
        stages["sbmlsim"] = StageResult("fail", error_message(err))

    # sbml2cellml
    roundtrip_path = work_dir / f"{case.case.id}-roundtrip.cellml"
    try:
        convert_sbml2cellml(sbml_path, cellml_path=roundtrip_path, validate=True)
        stages["sbml2cellml"] = StageResult("pass")
    except Exception as err:
        stages["sbml2cellml"] = StageResult("fail", error_message(err))
        stages["roundtrip"] = StageResult("skip", "sbml2cellml failed")
        return _result(informative)

    # roundtrip
    try:
        result = simulate_stage(
            libopencor,
            "simulate_cellml",
            cellml_path=str(roundtrip_path),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
        )
        df = requested_frame(frame(result), {}, settings)
        stages["roundtrip"] = stage_result(compare(df, expected, settings), result)
    except Exception as err:
        stages["roundtrip"] = StageResult("fail", error_message(err))

    return _result(informative)


def run_physiome(
    exposures: list[Exposure],
    work_dir: Path,
    cache: Path | None = None,
    timeout: float = 60.0,
    progress: Callable[[str], None] | None = None,
) -> SuiteResult:
    """Run the pipeline for every model of the selection.

    Args:
        exposures: the exposures of the selection.
        work_dir: directory for the converted files, created if needed.
        cache: cache root of the workspaces.
        timeout: seconds per simulator call.
        progress: called with the status line of every case.

    Returns:
        The result, with the stages of a run which starts from CellML.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    cases, skipped = prepare_cases(exposures, cache)
    result = SuiteResult(
        suite=SUITE_NAME,
        version=__version__,
        skipped=skipped,
        stages=CELLML_STAGES,
    )
    if not cases:
        return result
    with (
        SimulatorWorker("sbmlsim", timeout) as sbmlsim,
        SimulatorWorker("libopencor", timeout) as libopencor,
    ):
        for case in cases:
            logger.info("case %s", case.case.id)
            case_result = run_case(case, work_dir, sbmlsim, libopencor)
            result.cases[case.case.id] = case_result
            if progress is not None:
                statuses = " ".join(
                    f"{stage}={case_result.stages[stage].status}"
                    for stage in CELLML_STAGES
                )
                progress(f"{case.case.id} {statuses}")
    return result
