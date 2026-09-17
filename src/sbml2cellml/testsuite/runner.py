"""The pipeline of the harness.

Every runnable case goes through five stages: the reference simulation of
the original SBML with roadrunner, the conversion to CellML, the libopencor
simulation of the CellML, the conversion back to SBML and the roadrunner
simulation of the roundtrip SBML. Every simulation is compared with the
expected results of the case. The simulators run in worker processes, the
conversions in this process.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import libsbml

from sbml2cellml import __version__, convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.testsuite.cases import SUITE_VERSION, Case, skip_reason
from sbml2cellml.testsuite.compare import (
    Comparison,
    compare,
    requested_frame,
    species_quantities,
    strip_brackets,
)
from sbml2cellml.testsuite.results import STAGES, CaseResult, StageResult, SuiteResult
from sbml2cellml.testsuite.worker import SimulatorWorker, frame

logger = logging.getLogger(__name__)

#: length of a failure message
MESSAGE_LENGTH = 200
#: tight solver tolerances so the comparison measures the conversion, not the
#: integrator; passed to every roadrunner and libopencor simulation
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-12


def _message(err: BaseException) -> str:
    """Type and first line of an exception, shortened.

    When the first line ends with `:` (e.g. a `CellMLValidationError` whose
    message continues with the list of issues), the second line is appended
    too, so the message carries the first issue instead of just the count.
    """
    lines = str(err).strip().splitlines()
    first = lines[0] if lines else ""
    if first.endswith(":") and len(lines) > 1:
        first = f"{first} {lines[1].strip()}"
    return f"{type(err).__name__}: {first}"[:MESSAGE_LENGTH]


def _stage(comparison: Comparison) -> StageResult:
    """Stage result of a comparison."""
    return StageResult(
        "pass" if comparison.passed else "fail",
        comparison.message[:MESSAGE_LENGTH],
        None if not comparison.variables else comparison.max_excess,
    )


def reference_selections(case: Case, model: libsbml.Model) -> list[str]:
    """Roadrunner selections of the settings variables of the original model.

    A species expected as concentration is selected as `[id]`, everything
    else by id.
    """
    species = {s.getId() for s in model.getListOfSpecies()}
    return [
        f"[{v}]" if v in species and v in case.settings.concentration else v
        for v in case.settings.variables
    ]


def run_case(
    case: Case, work_dir: Path, roadrunner: SimulatorWorker, libopencor: SimulatorWorker
) -> CaseResult:
    """Run the five stages of a case.

    Args:
        case: a runnable case.
        work_dir: directory for the converted files.
        roadrunner: worker for the SBML simulations.
        libopencor: worker for the CellML simulation.

    Returns:
        The stage results; a stage whose input stage failed is `skip`. Every
        stage is `fail` when the case itself cannot be set up (e.g. an
        unparsable SBML file).
    """
    assert case.sbml_path is not None
    settings = case.settings
    try:
        model = libsbml.readSBMLFromFile(str(case.sbml_path)).getModel()
        if model is None:
            raise ValueError("no model in the SBML file")
        quantities = species_quantities(model)
        compartments = [c.getId() for c in model.getListOfCompartments()]
    except Exception as err:
        message = f"setup: {_message(err)}"[:MESSAGE_LENGTH]
        stages = {stage: StageResult("fail", message) for stage in STAGES}
        return CaseResult(
            case.id, list(case.test_tags), list(case.component_tags), stages
        )

    stages: dict[str, StageResult] = {}

    # reference
    try:
        result = roadrunner.call(
            "simulate_sbml",
            sbml=case.sbml_path.read_text(encoding="utf-8"),
            selections=reference_selections(case, model),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
            relative_tolerance=RELATIVE_TOLERANCE,
            absolute_tolerance=ABSOLUTE_TOLERANCE,
        )
        stages["reference"] = _stage(
            compare(strip_brackets(frame(result)), case.expected, settings)
        )
    except Exception as err:
        stages["reference"] = StageResult("fail", _message(err))

    # sbml2cellml
    cellml_path = work_dir / f"{case.id}.cellml"
    try:
        convert_sbml2cellml(case.sbml_path, cellml_path=cellml_path, validate=True)
        stages["sbml2cellml"] = StageResult("pass")
    except Exception as err:
        stages["sbml2cellml"] = StageResult("fail", _message(err))
        for stage in ("libopencor", "cellml2sbml", "roundtrip"):
            stages[stage] = StageResult("skip", "sbml2cellml failed")
        return CaseResult(
            case.id, list(case.test_tags), list(case.component_tags), stages
        )

    # libopencor
    try:
        result = libopencor.call(
            "simulate_cellml",
            cellml_path=str(cellml_path),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
            relative_tolerance=RELATIVE_TOLERANCE,
            absolute_tolerance=ABSOLUTE_TOLERANCE,
        )
        df = requested_frame(frame(result), quantities, settings)
        stages["libopencor"] = _stage(compare(df, case.expected, settings))
    except Exception as err:
        stages["libopencor"] = StageResult("fail", _message(err))

    # cellml2sbml
    roundtrip_path = work_dir / f"{case.id}-roundtrip.xml"
    try:
        convert_cellml2sbml(cellml_path, sbml_path=roundtrip_path, validate=True)
        stages["cellml2sbml"] = StageResult("pass")
    except Exception as err:
        stages["cellml2sbml"] = StageResult("fail", _message(err))
        stages["roundtrip"] = StageResult("skip", "cellml2sbml failed")
        return CaseResult(
            case.id, list(case.test_tags), list(case.component_tags), stages
        )

    # roundtrip
    try:
        selections = list(dict.fromkeys([*settings.variables, *compartments]))
        result = roadrunner.call(
            "simulate_sbml",
            sbml=roundtrip_path.read_text(encoding="utf-8"),
            selections=selections,
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
            relative_tolerance=RELATIVE_TOLERANCE,
            absolute_tolerance=ABSOLUTE_TOLERANCE,
        )
        df = requested_frame(frame(result), quantities, settings)
        stages["roundtrip"] = _stage(compare(df, case.expected, settings))
    except Exception as err:
        stages["roundtrip"] = StageResult("fail", _message(err))

    return CaseResult(case.id, list(case.test_tags), list(case.component_tags), stages)


def run_suite(
    cases: list[Case],
    work_dir: Path,
    timeout: float = 60.0,
    progress: Callable[[str], None] | None = None,
) -> SuiteResult:
    """Run the pipeline for every runnable case.

    Args:
        cases: the cases; unrunnable ones are recorded as skipped.
        work_dir: directory for the converted files, created if needed.
        timeout: seconds per simulator call.
        progress: called with the case id after every runnable case.

    Returns:
        The suite result.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    result = SuiteResult(suite=SUITE_VERSION, version=__version__)
    runnable = []
    for case in cases:
        reason = skip_reason(case)
        if reason is None:
            runnable.append(case)
        else:
            result.skipped[case.id] = reason
    if not runnable:
        return result
    with (
        SimulatorWorker("roadrunner", timeout) as roadrunner,
        SimulatorWorker("libopencor", timeout) as libopencor,
    ):
        for case in runnable:
            logger.info("case %s", case.id)
            result.cases[case.id] = run_case(case, work_dir, roadrunner, libopencor)
            if progress is not None:
                progress(case.id)
    return result
