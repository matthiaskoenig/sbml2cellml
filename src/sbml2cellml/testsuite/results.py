"""Results of a suite run: per case and stage, JSON, regressions."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: the stages of the pipeline of the test suite, in order: the SBML model
#: is the source, its simulation gives the expected results
STAGES = ("sbmlsim", "sbml2cellml", "libopencor", "cellml2sbml", "roundtrip")
#: the stages of a pipeline whose source is the CellML model (`physiome`),
#: where the simulation of that model gives the expected results
CELLML_STAGES = ("libopencor", "cellml2sbml", "sbmlsim", "sbml2cellml", "roundtrip")
#: possible statuses of a stage
STATUSES = ("pass", "fail", "skip")


@dataclass
class StageResult:
    """Outcome of one stage of one case."""

    status: str
    message: str = ""
    max_excess: float | None = None
    #: wall time of the integration of the stage in seconds, measured in
    #: the worker process inside the simulator wrapper; `None` for a stage
    #: without a simulation and for a simulation which failed
    seconds: float | None = None
    #: wall time of everything the simulator does with the model before it
    #: integrates (reading and converting the file, compiling the model,
    #: building the instance), in seconds
    setup_seconds: float | None = None


@dataclass
class CaseResult:
    """Outcome of one case."""

    id: str
    test_tags: list[str]
    component_tags: list[str]
    stages: dict[str, StageResult]
    name: str = ""
    #: whether the expected frame moves more than the tolerance band for at
    #: least one variable (`sbml2cellml.testsuite.compare.is_informative`);
    #: `None` when there is no expected frame, i.e. the `sbmlsim` stage
    #: failed for a case without expected results of its own
    informative: bool | None = None


@dataclass
class SuiteResult:
    """Outcome of a suite run."""

    suite: str
    version: str
    cases: dict[str, CaseResult] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    #: the stages of the pipeline in the order they ran, which is `STAGES`
    #: for a run whose source is the SBML model and `CELLML_STAGES` for one
    #: whose source is the CellML model
    stages: tuple[str, ...] = STAGES

    def seconds(self, stage: str, setup: bool = False) -> dict[str, float]:
        """Wall time of the simulations of a stage, by case.

        Args:
            stage: name of the stage.
            setup: the setup of the simulator instead of the integration.

        Returns:
            The seconds of every case whose stage was simulated and timed,
            by case id.
        """
        timed = {}
        for cid, case in self.cases.items():
            result = case.stages.get(stage)
            seconds = (
                None
                if result is None
                else (result.setup_seconds if setup else result.seconds)
            )
            if seconds is not None:
                timed[cid] = seconds
        return timed

    def counts(self, stage: str) -> dict[str, int]:
        """Number of cases per status of a stage."""
        counts = dict.fromkeys(STATUSES, 0)
        for case in self.cases.values():
            counts[case.stages[stage].status] += 1
        return counts

    def to_json(self, path: Path) -> None:
        """Write the result as JSON, sorted and indented (deterministic).

        `max_excess` is rounded to 3 significant digits: its exact value is
        an artifact of the solver and the machine it ran on, so keeping the
        full precision would churn thousands of lines on every regeneration.
        """
        cases = {}
        for cid, case in sorted(self.cases.items()):
            case_data = asdict(case)
            for stage in case_data["stages"].values():
                if stage["max_excess"] is not None:
                    stage["max_excess"] = float(f"{stage['max_excess']:.3g}")
                # the wall time differs from run to run anyway, three
                # significant digits keep the committed file readable
                for key in ("seconds", "setup_seconds"):
                    if stage[key] is not None:
                        stage[key] = float(f"{stage[key]:.3g}")
            cases[cid] = case_data
        data: dict[str, Any] = {
            "suite": self.suite,
            "version": self.version,
            "stages": list(self.stages),
            "cases": cases,
            "skipped": dict(sorted(self.skipped.items())),
        }
        Path(path).write_text(
            json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )

    @classmethod
    def from_json(cls, path: Path) -> "SuiteResult":
        """Read a result written by `to_json`."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cases = {
            cid: CaseResult(
                id=case["id"],
                test_tags=list(case["test_tags"]),
                component_tags=list(case["component_tags"]),
                stages={
                    name: StageResult(**stage) for name, stage in case["stages"].items()
                },
                name=case.get("name", ""),
                informative=case.get("informative"),
            )
            for cid, case in data["cases"].items()
        }
        return cls(
            suite=data["suite"],
            version=data["version"],
            cases=cases,
            skipped=dict(data["skipped"]),
            stages=tuple(data.get("stages", STAGES)),
        )


def cellml_first(result: SuiteResult) -> bool:
    """Whether the source of a run is the CellML model and not the SBML one.

    Args:
        result: a suite run.

    Returns:
        Whether the simulation of the CellML model gives the expected
        results, as in the Physiome check.
    """
    return bool(result.stages) and result.stages[0] == "libopencor"


def comparison_stage(result: SuiteResult) -> str:
    """The stage which compares the converted model with the expected results.

    The source of a run is simulated for the expected results, the model of
    the other language is compared with them: `libopencor` simulates the
    CellML model of a run which starts from SBML, `sbmlsim` the SBML model
    of a run which starts from CellML.

    Args:
        result: a suite run.

    Returns:
        The name of the stage.
    """
    return "sbmlsim" if cellml_first(result) else "libopencor"


def regressions(old: SuiteResult, new: SuiteResult) -> list[str]:
    """Stages which passed before and do not pass now, and missing cases.

    A stage which only one of the two results has (e.g. after a stage was
    renamed) is left out of the comparison: it has no status to compare
    with.

    Args:
        old: committed result.
        new: current result.

    Returns:
        One line per regression, e.g. `00001 roundtrip: pass -> fail (message)`.
    """
    lines: list[str] = []
    for cid, case in sorted(old.cases.items()):
        if cid not in new.cases:
            lines.append(f"{cid}: missing")
            continue
        for stage in new.stages:
            before = case.stages.get(stage)
            after = new.cases[cid].stages.get(stage)
            if before is None or after is None:
                continue
            if before.status == "pass" and after.status != "pass":
                lines.append(f"{cid} {stage}: pass -> {after.status} ({after.message})")
    return lines


def improvements(old: SuiteResult, new: SuiteResult) -> list[str]:
    """Stages which did not pass before and pass now.

    A stage which only one of the two results has is left out, as in
    `regressions`.
    """
    lines: list[str] = []
    for cid, case in sorted(new.cases.items()):
        if cid not in old.cases:
            lines.append(f"{cid}: new")
            continue
        for stage in new.stages:
            before = old.cases[cid].stages.get(stage)
            after = case.stages.get(stage)
            if before is None or after is None:
                continue
            if before.status != "pass" and after.status == "pass":
                lines.append(f"{cid} {stage}: {before.status} -> pass")
    return lines
