"""Results of a suite run: per case and stage, JSON, regressions."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: the stages of the pipeline, in order
STAGES = ("reference", "sbml2cellml", "libopencor", "cellml2sbml", "roundtrip")
#: possible statuses of a stage
STATUSES = ("pass", "fail", "skip")


@dataclass
class StageResult:
    """Outcome of one stage of one case."""

    status: str
    message: str = ""
    max_excess: float | None = None


@dataclass
class CaseResult:
    """Outcome of one case."""

    id: str
    test_tags: list[str]
    component_tags: list[str]
    stages: dict[str, StageResult]
    name: str = ""


@dataclass
class SuiteResult:
    """Outcome of a suite run."""

    suite: str
    version: str
    cases: dict[str, CaseResult] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

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
            cases[cid] = case_data
        data: dict[str, Any] = {
            "suite": self.suite,
            "version": self.version,
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
            )
            for cid, case in data["cases"].items()
        }
        return cls(
            suite=data["suite"],
            version=data["version"],
            cases=cases,
            skipped=dict(data["skipped"]),
        )


def regressions(old: SuiteResult, new: SuiteResult) -> list[str]:
    """Stages which passed before and do not pass now, and missing cases.

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
        for stage in STAGES:
            before = case.stages[stage].status
            after = new.cases[cid].stages[stage]
            if before == "pass" and after.status != "pass":
                lines.append(f"{cid} {stage}: pass -> {after.status} ({after.message})")
    return lines


def improvements(old: SuiteResult, new: SuiteResult) -> list[str]:
    """Stages which did not pass before and pass now."""
    lines: list[str] = []
    for cid, case in sorted(new.cases.items()):
        if cid not in old.cases:
            lines.append(f"{cid}: new")
            continue
        for stage in STAGES:
            before = old.cases[cid].stages[stage].status
            if before != "pass" and case.stages[stage].status == "pass":
                lines.append(f"{cid} {stage}: {before} -> pass")
    return lines
