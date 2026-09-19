"""Markdown report of a suite run, the page `docs/testsuite.md`."""

import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from sbml2cellml.testsuite.figure import dark_path, write_figures
from sbml2cellml.testsuite.results import STAGES, SuiteResult
from sbml2cellml.testsuite.runner import SOLVER_SETTINGS

#: intro paragraphs of the SBML test suite report
TESTSUITE_INTRO = (
    "Semantic test cases of the [SBML test suite](https://github.com/sbmlteam/sbml-test-suite) "
    "{suite}. Every case is simulated with roadrunner (`roadrunner`), converted to "
    "CellML (`sbml2cellml`), simulated with libopencor (`libopencor`), converted back to SBML "
    "(`cellml2sbml`) and simulated with roadrunner again (`roundtrip`). See "
    "[Development](development.md#sbml-test-suite) for how to run it.\n\n"
    "Every simulation is compared with the expected results of the case: a value passes when "
    "`|value - expected| <= absolute + relative * |expected|` with the absolute and the "
    "relative tolerance of the settings of the case. {solver}\n\n"
    "A `roadrunner` failure means roadrunner itself cannot simulate the case (algebraic rules, "
    "delays), it says nothing about the converters."
)
#: bar diagram of the SBML test suite report, relative to the report; written
#: by `sbml2cellml.testsuite.figure.write_figures`
TESTSUITE_FIGURE = "images/testsuite.svg"
#: reason of the cases whose values exceed the tolerance of the comparison
MISMATCH = "numerical mismatch"
#: quoted text, e.g. the formula of an algebraic rule roadrunner does not support
_QUOTED = re.compile(r"'[^']*'")
#: a number preceded by a space, `(`, `,` or `=`, so identifiers such as
#: `S1` are left untouched; `nan` and `inf` count as numbers too
_NUMBER = re.compile(r"(?<=[ (,=])(?:nan|inf|[\d][\d.e+-]*)")
#: a tolerance failure, whose variable names are not the cause
_TOLERANCE = re.compile(r"exceeds the tolerance")


def tolerance_text(value: float) -> str:
    """A tolerance as it is written in the documentation, e.g. `1e-9`.

    Args:
        value: a tolerance.

    Returns:
        The scientific notation without the zeros of the mantissa and the
        exponent, e.g. `1e-3` and `2.5e-4`.
    """
    mantissa, exponent = f"{value:e}".split("e")
    return f"{mantissa.rstrip('0').rstrip('.')}e{int(exponent)}"


def solver_text() -> str:
    """Sentences on the solver settings of the simulations of a report.

    Returns:
        The tolerances and the number of internal steps of
        `sbml2cellml.testsuite.runner.SOLVER_SETTINGS`, so that the reports
        document the settings the simulations ran with.
    """
    tight, *relaxed = (
        f"`{tolerance_text(settings['relative_tolerance'])}`/"
        f"`{tolerance_text(settings['absolute_tolerance'])}`"
        for settings in SOLVER_SETTINGS
    )
    steps = SOLVER_SETTINGS[0]["maximum_number_of_steps"]
    return (
        "Both simulators integrate with CVODE with tight tolerances "
        f"(relative/absolute {tight}) and up to {steps} internal steps between "
        "two time points, so the comparison measures the conversion and not "
        "the integrator; only when CVODE gives up with these tolerances the "
        f"simulation is repeated with {' and '.join(relaxed)}."
    )


def _cell(text: str) -> str:
    """Escape a text for a markdown table cell.

    Args:
        text: free text, e.g. a failure reason (libopencor joins its issues
            with ` | `) or a model name.

    Returns:
        The text with `|` escaped, so it does not split the cell.
    """
    return text.replace("|", "\\|")


def _reason(message: str) -> str:
    """Group key of a failure message.

    Args:
        message: a stage failure message, possibly of several lines.

    Returns:
        For a message containing `[ERROR]` (a `CellMLValidationError`, a
        line on the model followed by the libcellml issues), the exception
        type plus the first issue, so messages differing only in the model
        name, path and the number and the rest of the issues are one group.
        For a tolerance failure (`... exceeds the tolerance ...`), the single
        reason `MISMATCH`, since the variable name is not the cause.
        Otherwise the first line of the message. Quoted text and numbers
        (including `nan` and `inf`) are dropped from the key and whitespace
        is collapsed. The key only groups the cases, the report shows the
        complete messages.
    """
    if _TOLERANCE.search(message):
        return MISMATCH
    if "[ERROR]" in message:
        exception_type = message.split(":", 1)[0]
        # nothing may follow the marker, so no index into the lines
        issue = message.split("[ERROR]", 1)[1].strip().split("\n", 1)[0]
        reason = f"{exception_type}: {issue}"
    else:
        reason = message.strip().split("\n", 1)[0]
    reason = _QUOTED.sub("''", reason)
    reason = _NUMBER.sub("N", reason)
    return " ".join(reason.split())


def _errors(result: SuiteResult, ids: list[str], stage: str) -> list[str]:
    """Fenced block with the complete failure messages of cases.

    Args:
        result: a suite run.
        ids: ids of cases which fail the stage.
        stage: a stage.

    Returns:
        The lines of the block, `id: message` per case; the further lines of
        a message are indented. A fenced block shows the message verbatim,
        whatever markdown syntax it contains.
    """
    lines = ["```text"]
    for cid in ids:
        first, *rest = result.cases[cid].stages[stage].message.split("\n")
        lines.append(f"{cid}: {first}")
        lines += [f"    {line}" if line else "" for line in rest]
    lines.append("```")
    return lines


def render_report(
    result: SuiteResult,
    title: str = "SBML test suite",
    intro: str = TESTSUITE_INTRO,
    command: str = "sbml2cellml-testsuite",
    names: bool = False,
    figure: str | None = None,
) -> str:
    """Render the report.

    Args:
        result: a suite run.
        title: page title, the level-1 heading.
        intro: intro text right after the title; `{suite}` is replaced with
            `result.suite` and `{solver}` with `solver_text`.
        command: command named in the generated-by header.
        names: whether the cases table gets a `name` column.
        figure: path of the bar diagram relative to the report, shown in the
            summary together with its variant for dark backgrounds
            (`sbml2cellml.testsuite.figure`); no figure when `None`.

    Returns:
        The markdown page.
    """
    lines: list[str] = [
        f"<!-- generated by {command}, do not edit -->",
        f"# {title}",
        "",
        intro.format(suite=result.suite, solver=solver_text()),
        "",
        "## Summary",
        "",
        f"{len(result.cases)} cases run, {len(result.skipped)} skipped.",
        "",
    ]
    if figure is not None:
        # the site shows the variant matching its color scheme
        alt = "Cases which pass, fail and skip the stages"
        dark = dark_path(PurePosixPath(figure))
        lines += [
            f"![{alt}]({figure}#only-light)",
            f"![{alt}]({dark}#only-dark)",
            "",
        ]
    lines += [
        "| stage | total | pass | fail | skip | pass rate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    total = len(result.cases)
    for stage in STAGES:
        counts = result.counts(stage)
        lines.append(
            f"| {stage} | {total} | {counts['pass']} | {counts['fail']} | "
            f"{counts['skip']} | {100 * counts['pass'] / (total or 1):.1f}% |"
        )

    passing_libopencor = [
        case
        for case in result.cases.values()
        if case.stages["libopencor"].status == "pass"
    ]
    if passing_libopencor:
        informative = sum(1 for case in passing_libopencor if case.informative)
        lines += [
            "",
            f"{informative} of the {len(passing_libopencor)} cases with a passing "
            "libopencor stage are informative: the expected results move more "
            "than the tolerance band for at least one variable.",
        ]

    lines += [
        "",
        "## Failure reasons",
        "",
        "The cases which fail a stage, grouped by their error: errors which "
        "differ only in quoted text, numbers and, for the validation of a "
        "CellML model, the issues after the first one are one group. Every "
        "case is listed with its complete error.",
        "",
    ]
    for stage in STAGES:
        groups: dict[str, list[str]] = defaultdict(list)
        for cid, case in sorted(result.cases.items()):
            stage_result = case.stages[stage]
            if stage_result.status == "fail":
                groups[_reason(stage_result.message)].append(cid)
        if not groups:
            continue
        failed = sum(len(ids) for ids in groups.values())
        lines += [f"### {stage}", "", f"{failed} of {total} cases fail.", ""]
        for reason, ids in sorted(
            groups.items(), key=lambda item: (-len(item[1]), item[0])
        ):
            cases = "1 case" if len(ids) == 1 else f"{len(ids)} cases"
            if reason == MISMATCH:
                cases += f", {MISMATCH}"
            lines += [f"**{cases}**", "", *_errors(result, ids, stage), ""]
        mismatch_ids = groups.get(MISMATCH, [])
        if mismatch_ids:
            tag_groups: dict[str, list[str]] = defaultdict(list)
            for cid in mismatch_ids:
                tags = ", ".join(sorted(set(result.cases[cid].test_tags)))
                tag_groups[tags].append(cid)
            # omitted when every group is empty (e.g. BioModels cases, which
            # carry no test tags), since the table would say nothing then
            if any(tag_groups):
                lines += [
                    f"The test tags of the cases with a {MISMATCH}:",
                    "",
                    "| tags | cases | ids |",
                    "| --- | --- | --- |",
                ]
                for tags, ids in sorted(
                    tag_groups.items(), key=lambda item: (-len(item[1]), item[0])
                ):
                    lines.append(f"| {tags} | {len(ids)} | {', '.join(ids)} |")
                lines.append("")

    lines += ["## Skipped cases", "", "| reason | cases |", "| --- | --- |"]
    for reason, count in sorted(Counter(result.skipped.values()).items()):
        lines.append(f"| {_cell(reason)} | {count} |")

    name_header = "name | " if names else ""
    name_sep = "--- | " if names else ""
    lines += [
        "",
        "## Cases",
        "",
        f"| case | {name_header}components | "
        + " | ".join(STAGES)
        + " | informative |",
        f"| --- | {name_sep}--- | " + " | ".join("---" for _ in STAGES) + " | --- |",
    ]
    for cid, case in sorted(result.cases.items()):
        statuses = " | ".join(case.stages[stage].status for stage in STAGES)
        name_cell = f"{_cell(case.name)} | " if names else ""
        if case.informative is None:
            informative_cell = ""
        else:
            informative_cell = "yes" if case.informative else "no"
        lines.append(
            f"| {cid} | {name_cell}{', '.join(case.component_tags)} | "
            f"{statuses} | {informative_cell} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(
    result: SuiteResult,
    path: Path,
    title: str = "SBML test suite",
    intro: str = TESTSUITE_INTRO,
    command: str = "sbml2cellml-testsuite",
    names: bool = False,
    figure: str | None = None,
    figure_title: str | None = None,
    figure_cases: str = "cases",
) -> None:
    """Write the report and, with `figure`, its bar diagram.

    Args:
        result: a suite run.
        path: markdown file, overwritten.
        title: page title, the level-1 heading.
        intro: intro text right after the title; `{suite}` is replaced with
            `result.suite` and `{solver}` with `solver_text`.
        command: command named in the generated-by header.
        names: whether the cases table gets a `name` column.
        figure: path of the bar diagram relative to the report, written for
            light and dark backgrounds; no figure when `None`.
        figure_title: start of the title of the figure, the SBML test suite
            with its version when `None`.
        figure_cases: what a case is in the figure, e.g. `models`.
    """
    path = Path(path)
    path.write_text(
        render_report(
            result,
            title=title,
            intro=intro,
            command=command,
            names=names,
            figure=figure,
        ),
        encoding="utf-8",
    )
    if figure is not None:
        write_figures(
            result, path.parent / figure, title=figure_title, cases=figure_cases
        )
