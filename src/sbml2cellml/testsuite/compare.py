"""Comparison of a simulation with the expected results of a case.

The SBML test suite accepts a value when
`|value - expected| <= absolute + relative * |expected|` at every time point,
with the tolerances of the case. Species are expected either as amounts or
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
        error = np.abs(values - target)
        error = np.where(np.isnan(error), np.inf, error)
        tolerance = settings.absolute + settings.relative * np.abs(target)
        excess = float(np.max(error - tolerance))
        passed = excess <= 0
        comparisons.append(
            VariableComparison(variable, float(np.max(error)), excess, passed)
        )
        if not passed:
            failures.append(f"{variable} exceeds the tolerance by {excess:.3g}")
    return Comparison(tuple(comparisons), not failures, "; ".join(failures))


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
        CompareError: a variable needs converting between amount and
            concentration and its compartment column is missing from `df`.
    """
    out = pd.DataFrame({TIME: df[TIME]})
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
        out[variable] = values.to_numpy()
    return out


def strip_brackets(df: pd.DataFrame) -> pd.DataFrame:
    """Rename roadrunner's `[S]` concentration columns to `S`."""
    return df.rename(
        columns={
            c: c[1:-1] for c in df.columns if c.startswith("[") and c.endswith("]")
        }
    )
