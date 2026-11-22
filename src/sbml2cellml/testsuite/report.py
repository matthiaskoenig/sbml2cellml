"""Markdown report of a suite run, the page `docs/testsuite.md`."""

import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from statistics import median

from sbml2cellml.testsuite.figure import (
    dark_path,
    timing_pairs,
    write_figures,
    write_timing_figures,
)
from sbml2cellml.testsuite.results import STAGES, SuiteResult
from sbml2cellml.testsuite.runner import SOLVER_SETTINGS

#: intro paragraphs of the SBML test suite report
TESTSUITE_INTRO = (
    "Semantic test cases of the [SBML test suite](https://github.com/sbmlteam/sbml-test-suite) "
    "at commit [`{suite}`](https://github.com/sbmlteam/sbml-test-suite/commit/{suite}). Every "
    "case is simulated with [sbmlsim-core](https://matthiaskoenig.github.io/sbmlsim-core/) "
    "(`sbmlsim`), converted to "
    "CellML (`sbml2cellml`), simulated with libopencor (`libopencor`), converted back to SBML "
    "(`cellml2sbml`) and simulated with sbmlsim-core again (`roundtrip`). See "
    "[Development](development.md#sbml-test-suite) for how to run it.\n\n"
    "Every simulation is compared with the expected results of the case: a value passes when "
    "`|value - expected| <= absolute + relative * |expected|` with the absolute and the "
    "relative tolerance of the settings of the case. {solver}\n\n"
    "An `sbmlsim` failure means sbmlsim-core itself cannot simulate the case, it says nothing "
    "about the converters."
)
#: bar diagram of the SBML test suite report, relative to the report; written
#: by `sbml2cellml.testsuite.figure.write_figures`
TESTSUITE_FIGURE = "images/testsuite.svg"
#: heading of the timing section, without the `##` of the markdown
TIMINGS_HEADING = "Timings"
#: the stages with a simulation, with the simulator and the model they time
TIMED_STAGES = (
    ("sbmlsim", "sbmlsim-core", "SBML model"),
    ("libopencor", "libopencor", "CellML model"),
    ("roundtrip", "sbmlsim-core", "roundtrip SBML model"),
)
#: reason of the cases whose values exceed the tolerance of the comparison
MISMATCH = "numerical mismatch"
#: quoted text, e.g. the formula of an algebraic rule a simulator does not support
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
        f"simulation is repeated with {' and '.join(relaxed)}. Both "
        "simulations scale the absolute tolerance with the smallest initial "
        "value of a state of their own model when it is below one: the "
        "states of the SBML side are amounts, which are small for a model "
        "with a small compartment, and the states of the CellML side the "
        "variables of its components."
    )


def timings_figure(figure: str) -> str:
    """Path of the timing figure next to the bar diagram.

    Args:
        figure: path of the bar diagram, e.g. `images/testsuite.svg`.

    Returns:
        The path with `_timings` added to the file name, e.g.
        `images/testsuite_timings.svg`.
    """
    path = PurePosixPath(figure)
    return str(path.with_name(f"{path.stem}_timings{path.suffix}"))


def duration_text(seconds: float) -> str:
    """A wall time as it is written in the reports.

    Args:
        seconds: a wall time.

    Returns:
        Milliseconds below one second, with a decimal below ten
        milliseconds, seconds below a minute and minutes above it, e.g.
        `1.4 ms`, `18 ms`, `2.4 s`, `3.1 min`.
    """
    if seconds < 0.01:
        return f"{seconds * 1e3:.1f} ms"
    if seconds < 1.0:
        return f"{seconds * 1e3:.0f} ms"
    if seconds < 60.0:
        return f"{seconds:.1f} s"
    return f"{seconds / 60.0:.1f} min"


def _quantile(values: list[float], fraction: float) -> float:
    """Value at a fraction of the sorted values, the nearest rank.

    Args:
        values: the values, not empty.
        fraction: the fraction, e.g. `0.95`.

    Returns:
        The value at the fraction.
    """
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def timing_lines(result: SuiteResult, figure: str | None = None) -> list[str]:
    """Lines of the timing section of a report.

    Args:
        result: a suite run.
        figure: path of the timing figure relative to the report, shown with
            its variant for dark backgrounds; no figure when `None`.

    Returns:
        The markdown lines, empty when no simulation of the run was timed.
    """
    timed = {stage: result.seconds(stage) for stage, _, _ in TIMED_STAGES}
    if not any(timed.values()):
        return []
    lines = [
        f"## {TIMINGS_HEADING}",
        "",
        "Wall time of the simulations which pass or fail, measured inside "
        "the simulator wrapper in the worker process, so it holds no "
        "overhead of the harness. The setup is everything a simulator does "
        "with the model before it integrates: reading and converting the "
        "file, compiling the model and building the instance. Both "
        "simulators cache what they compiled, so a model simulated again in "
        "the same process needs no setup; every case here is set up once. "
        "Both of them run the model once before the run of the result, so "
        "that the generation of the code of a model, which libopencor does "
        "when it runs the model the first time, is part of the setup.",
        "",
        "The two simulators integrate with the same relative tolerance and "
        "with an absolute tolerance scaled to the states of their own model "
        "(amounts for the SBML model, the variables of the components for "
        "the CellML model), so neither of them is given an easier problem.",
        "",
    ]
    if figure is not None:
        alt = "Integration time of libopencor against sbmlsim-core per case"
        dark = dark_path(PurePosixPath(figure))
        lines += [
            f"![{alt}]({figure}#only-light)",
            f"![{alt}]({dark}#only-dark)",
            "",
        ]
    lines += [
        "| stage | simulator | model | simulations | setup median | "
        "integration median | integration p95 | integration slowest | "
        "integration total |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for stage, simulator, model in TIMED_STAGES:
        seconds = list(timed[stage].values())
        if not seconds:
            continue
        setup = list(result.seconds(stage, setup=True).values())
        lines.append(
            f"| {stage} | {simulator} | {model} | {len(seconds)} | "
            f"{duration_text(median(setup)) if setup else '-'} | "
            f"{duration_text(median(seconds))} | "
            f"{duration_text(_quantile(seconds, 0.95))} | "
            f"{duration_text(max(seconds))} | "
            f"{duration_text(sum(seconds))} |"
        )
    pairs = timing_pairs(result)
    if pairs:
        ratios = [libopencor / sbmlsim for sbmlsim, libopencor in pairs.values()]
        # as in the figure, which splits the points by the two times
        faster = sum(
            1 for sbmlsim, libopencor in pairs.values() if libopencor <= sbmlsim
        )
        middle = median(ratios)
        comparison = (
            f"{1 / middle:.1f} times faster"
            if middle < 1.0
            else f"{middle:.1f} times slower"
        )
        lines += [
            "",
            f"The two simulators integrate the same dynamics for {len(pairs)} "
            "cases, those whose CellML model reproduces the expected results. "
            f"libopencor is {comparison} than sbmlsim-core for the median of "
            f"them and faster for {faster}; over these cases the medians are "
            f"{duration_text(median([pair[0] for pair in pairs.values()]))} "
            "for sbmlsim-core and "
            f"{duration_text(median([pair[1] for pair in pairs.values()]))} "
            "for libopencor.",
        ]
    return [*lines, ""]


def without_timings(markdown: str) -> str:
    """A report without its timing section.

    The wall times of a run differ from run to run and from machine to
    machine, so the gating test of the full suite compares the committed
    report and the rendered one without them.

    Args:
        markdown: a rendered report.

    Returns:
        The report without the `## Timings` section, unchanged when it has
        none.
    """
    start = markdown.find(f"## {TIMINGS_HEADING}\n")
    if start < 0:
        return markdown
    end = markdown.find("## ", start + 3)
    return markdown[:start] + (markdown[end:] if end >= 0 else "")


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
            (`sbml2cellml.testsuite.figure`); the timing section shows
            `timings_figure` of it; no figure when `None`.

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

    lines += ["", *timing_lines(result, timings_figure(figure) if figure else None)]
    lines += [
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
            light and dark backgrounds, next to the timing figure
            (`timings_figure`); no figure when `None`.
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
        write_timing_figures(
            result,
            path.parent / timings_figure(figure),
            title=figure_title,
            cases=figure_cases,
        )
