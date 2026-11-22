"""The SBML reference simulator of the tests.

sbmlsim-core compiles the model to WebAssembly and simulates it in this
process, so the roundtrip tests need no simulator subprocess.
"""

import numpy as np

from sbml2cellml.testsuite.simulators import simulate_sbml as _simulate_sbml


def simulate_sbml(
    sbml: str, selections: list[str], start: float, end: float, steps: int
) -> np.ndarray:
    """sbmlsim-core timecourse of the selections.

    Returns the rows of the time points with the selections as columns, the
    time column excluded.
    """
    result = _simulate_sbml(sbml, selections, start, end, steps)
    return np.asarray(result["rows"])[:, 1:]
