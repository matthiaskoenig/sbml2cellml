"""Comparison of a simulation with the expected results of a case.

The SBML test suite accepts a value when
`|value - expected| <= absolute + relative * |expected|` at every time point,
with the tolerances of the case; the special values `inf`, `-inf` and `nan`
match only themselves. Species are expected either as amounts or
as concentrations (the `amount` and `concentration` lists of the settings);
a converted model carries every species in one quantity, so the columns are
converted with the compartment before the comparison.
"""

from dataclasses import dataclass

import libsbml
import numpy as np
import pandas as pd

from sbml2cellml.testsuite.cases import Settings

TIME = "time"


@dataclass(frozen=True)
class VariableComparison:
    """Result of one variable."""

    variable: str
    max_error: float
    max_excess: float
    passed: bool


@dataclass(frozen=True)
class Comparison:
    """Result of a case: every variable and the verdict."""

    variables: tuple[VariableComparison, ...]
    passed: bool
    message: str

    @property
    def max_excess(self) -> float:
        """Largest excess over the tolerance, negative when everything passes.

        `nan` for a structural failure without variables.
        """
        return max((v.max_excess for v in self.variables), default=float("nan"))


class CompareError(ValueError):
    """A result cannot be brought into the requested quantity."""


def _failed(message: str) -> Comparison:
    return Comparison(variables=(), passed=False, message=message)


def compare(
    result: pd.DataFrame, expected: pd.DataFrame, settings: Settings
) -> Comparison:
    """Compare a simulation with the expected results.

    Args:
        result: timecourse with a `time` column and the settings variables.
        expected: expected timecourse of the case.
        settings: settings of the case (variables and tolerances).

    Returns:
        The comparison; `passed` when every variable is within the tolerance
        at every time point.
    """
    if result.columns.duplicated().any() or expected.columns.duplicated().any():
        return _failed("duplicate column names")
    if len(result) != len(expected):
        return _failed(f"{len(result)} rows instead of {len(expected)}")
    if len(expected) == 0:
        return _failed("no rows")
    if TIME not in result.columns:
        return _failed("no time column")
    if not np.allclose(
        result[TIME].to_numpy(), expected[TIME].to_numpy(), rtol=1e-6, atol=1e-9
    ):
        return _failed("time points differ from the expected results")

    comparisons: list[VariableComparison] = []
    failures: list[str] = []
    for variable in settings.variables:
        if variable not in result.columns:
            return _failed(f"variable {variable} missing in the result")
        if variable not in expected.columns:
            return _failed(f"variable {variable} missing in the expected results")
        try:
            values = result[variable].to_numpy(dtype=float)
            target = expected[variable].to_numpy(dtype=float)
        except (ValueError, TypeError):
            return _failed(f"variable {variable} is not numeric")
        # special values (inf, -inf, nan) match only themselves, e.g. a
        # parameter initialised to inf or a ratio which is 0/0; any other
        # difference involving one is an infinite error, and the tolerance of
        # a special expected value is the absolute one, so the excess is never
        # nan (`Comparison.max_excess` could not rank it)
        with np.errstate(invalid="ignore"):
            same = (values == target) | (np.isnan(values) & np.isnan(target))
            error = np.where(same, 0.0, np.abs(values - target))
            error = np.where(np.isnan(error), np.inf, error)
            magnitude = np.where(np.isfinite(target), np.abs(target), 0.0)
            tolerance = settings.absolute + settings.relative * magnitude
            excess = float(np.max(error - tolerance))
        passed = excess <= 0
        comparisons.append(
            VariableComparison(variable, float(np.max(error)), excess, passed)
        )
        if not passed:
            failures.append(f"{variable} exceeds the tolerance by {excess:.3g}")
    return Comparison(tuple(comparisons), not failures, "; ".join(failures))


def is_informative(expected: pd.DataFrame, settings: Settings) -> bool:
    """Whether the expected results move more than the tolerance band.

    A case whose expected frame is (numerically) constant for every variable
    passes the comparison trivially no matter what the converters do; this
    flags that so it can be told apart from a genuine check.

    Args:
        expected: the expected frame, i.e. the case's expected results or,
            when there are none, the reference simulation.
        settings: settings of the case (variables and tolerances).

    Returns:
        True when at least one settings variable present in `expected` moves,
        between the minimum and maximum of its finite values, by more than
        `absolute + relative * max(|value|)`.
    """
    for variable in settings.variables:
        if variable not in expected.columns:
            continue
        values = expected[variable].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        tolerance = settings.absolute + settings.relative * float(
            np.max(np.abs(values))
        )
        if float(np.max(values)) - float(np.min(values)) > tolerance:
            return True
    return False


def species_quantities(model: libsbml.Model) -> dict[str, tuple[bool, str]]:
    """Quantity of the species variables of a converted model.

    Args:
        model: the original SBML model.

    Returns:
        Species id to `(has only substance units, compartment id)`: the
        converted variable is an amount when the flag is set, else a
        concentration.
    """
    return {
        species.getId(): (
            bool(species.getHasOnlySubstanceUnits()),
            species.getCompartment(),
        )
        for species in model.getListOfSpecies()
    }


def requested_frame(
    df: pd.DataFrame, quantities: dict[str, tuple[bool, str]], settings: Settings
) -> pd.DataFrame:
    """The settings variables in the quantity the case expects.

    Args:
        df: timecourse of a converted model (every variable a column,
            including the compartments).
        quantities: result of `species_quantities`.
        settings: settings of the case.

    Returns:
        `time` and the settings variables, species converted between amount
        and concentration with their compartment column when needed. A
        variable missing in `df` is left out (the comparison reports it).

    Raises:
        CompareError: `df` has no time column or duplicate column names (e.g.
            a parameter with the id `time` next to roadrunner's time), or a
            variable needs converting between amount and concentration and
            its compartment column is missing from `df`.
    """
    if TIME not in df.columns:
        raise CompareError("no time column in the simulation result")
    if df.columns.duplicated().any():
        raise CompareError("duplicate column names in the simulation result")
    # collected first and turned into a frame at once: inserting the columns
    # one by one fragments the frame (a PerformanceWarning of pandas)
    columns: dict[str, np.ndarray] = {TIME: df[TIME].to_numpy()}
    for variable in settings.variables:
        if variable not in df.columns:
            continue
        values = df[variable]
        if variable in quantities:
            in_amount, compartment = quantities[variable]
            want_amount = variable in settings.amount
            needs_conversion = in_amount != want_amount
            if needs_conversion and compartment not in df.columns:
                raise CompareError(
                    f"compartment {compartment} of {variable} missing, "
                    "cannot convert between amount and concentration"
                )
            if needs_conversion:
                size = df[compartment]
                if in_amount and not want_amount:
                    values = values / size
                elif not in_amount and want_amount:
                    values = values * size
        columns[variable] = values.to_numpy()
    return pd.DataFrame(columns, index=df.index)


def strip_brackets(df: pd.DataFrame) -> pd.DataFrame:
    """Rename roadrunner's `[S]` concentration columns to `S`."""
    return df.rename(
        columns={
            c: c[1:-1] for c in df.columns if c.startswith("[") and c.endswith("]")
        }
    )
