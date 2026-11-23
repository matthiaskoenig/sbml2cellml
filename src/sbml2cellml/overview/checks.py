"""The checks of the repository, their results and the links of their models.

A check runs models of one source through the five stages of the pipeline of
`sbml2cellml.testsuite.runner` and writes a results file. The stages differ
in their order (the SBML model is the source of the test suite and of
BioModels, the CellML model the source of the Physiome check), their roles
are the same: the source model is simulated for the expected results,
converted to the other language, the converted model is simulated and
compared, converted back and simulated again.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sbml2cellml.physiome.models import PHYSIOME_URL
from sbml2cellml.testsuite.results import SuiteResult

logger = logging.getLogger(__name__)

#: what the stages of a pipeline do, in the order of the stages; the name of
#: a stage differs between a check whose source is the SBML model and one
#: whose source is the CellML model, the role does not
ROLES = (
    "source simulated",
    "converted",
    "reproduces",
    "converted back",
    "roundtrip",
)
#: page of a model of BioModels; the REST API of the check uses
#: `www.biomodels.org`, which rejects no request of a script, the pages of
#: the models are served by the EBI
BIOMODELS_MODEL_URL = "https://www.ebi.ac.uk/biomodels/{id}"
#: page of an exposure of the Physiome Model Repository
PHYSIOME_MODEL_URL = f"{PHYSIOME_URL}/e/{{id}}"


@dataclass(frozen=True)
class Check:
    """One check of the repository and where its models come from."""

    #: name of the check, as in its results file
    name: str
    #: title of the check, the heading of its sections
    title: str
    #: short title, the label of the check in a figure
    short: str
    #: page of its report, relative to the pages of the documentation
    page: str
    #: its results file, relative to the repository
    results: Path
    #: the command which writes the results
    command: str
    #: what a case of the check is, `cases` or `models`
    unit: str
    #: where the models come from, one sentence
    source: str
    #: page of a model, `{id}` replaced with the id of the case; `None` for
    #: the cases of a test suite, which are no published models
    url: str | None = None

    def link(self, case_id: str) -> str:
        """A case id, linked to the page of its model when it has one.

        Args:
            case_id: id of a case of the check.

        Returns:
            The markdown link, or the id alone for a check without a url.
        """
        if self.url is None:
            return case_id
        return f"[{case_id}]({self.url.format(id=case_id)})"


#: the checks of the repository, in the order of their pages
CHECKS = (
    Check(
        name="testsuite",
        title="SBML test suite",
        short="SBML test suite",
        page="testsuite.md",
        results=Path("testsuite") / "results.json",
        command="sbml2cellml-testsuite",
        unit="cases",
        source=(
            "the semantic cases of the [SBML test suite]"
            "(https://github.com/sbmlteam/sbml-test-suite), small models "
            "written for one feature of SBML each, with the expected results "
            "of the suite"
        ),
    ),
    Check(
        name="biomodels",
        title="BioModels",
        short="BioModels",
        page="biomodels.md",
        results=Path("biomodels") / "results.json",
        command="sbml2cellml-biomodels",
        unit="models",
        source=(
            "the manually curated SBML models of "
            "[BioModels](https://www.biomodels.org), published models of "
            "systems biology"
        ),
        url=BIOMODELS_MODEL_URL,
    ),
    Check(
        name="physiome",
        title="Physiome Model Repository",
        short="Physiome",
        page="physiome.md",
        results=Path("physiome") / "results.json",
        command="sbml2cellml-physiome",
        unit="models",
        source=(
            "the CellML models of the [Physiome Model Repository]"
            f"({PHYSIOME_URL}), published models of physiology, most of them "
            "of many components"
        ),
        url=PHYSIOME_MODEL_URL,
    ),
)


@dataclass(frozen=True)
class Run:
    """The committed run of a check."""

    check: Check
    result: SuiteResult


def load_runs(results: dict[str, Path] | None = None) -> list[Run]:
    """Read the results of the checks.

    Args:
        results: results file per check name, the file of the check itself
            for a check which is not in the mapping; every path relative to
            the working directory.

    Returns:
        One run per check whose results file exists, in the order of
        `CHECKS`; a missing file is logged and left out, so the pages can be
        rendered from the checks which ran.
    """
    files = results or {}
    runs = []
    for check in CHECKS:
        path = Path(files.get(check.name, check.results))
        if not path.is_file():
            logger.warning("no results of the %s check: %s", check.name, path)
            continue
        runs.append(Run(check=check, result=SuiteResult.from_json(path)))
    return runs


def works(run: Run, case_id: str) -> bool:
    """Whether every stage of a case passes.

    Args:
        run: a run of a check.
        case_id: id of one of its cases.

    Returns:
        Whether the model is simulated, converted, reproduces the expected
        results, converted back and reproduces them again.
    """
    stages = run.result.cases[case_id].stages
    return all(stages[stage].status == "pass" for stage in run.result.stages)
