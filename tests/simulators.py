"""Simulators run in their own process.

roadrunner and libopencor bundle different LLVM versions and crash once both
have compiled in the same interpreter, so the roadrunner simulations of the
tests run in a subprocess and exchange their input and output as JSON.
"""

import json
import subprocess
import sys

import numpy as np

#: script run in the subprocess: reads the request from stdin, writes the result to stdout
ROADRUNNER_SCRIPT = """
import json, sys
import roadrunner
request = json.load(sys.stdin)
rr = roadrunner.RoadRunner(request["sbml"])
rr.timeCourseSelections = ["time", *request["selections"]]
result = rr.simulate(request["start"], request["end"], request["points"])
json.dump([list(map(float, row)) for row in result], sys.stdout)
"""


def simulate_sbml(
    sbml: str, selections: list[str], start: float, end: float, steps: int
) -> np.ndarray:
    """Roadrunner timecourse of the selections, run in a subprocess.

    Returns the rows of the time points with the selections as columns, the
    time column excluded.
    """
    request = {
        "sbml": sbml,
        "selections": selections,
        "start": start,
        "end": end,
        "points": steps + 1,
    }
    completed = subprocess.run(
        [sys.executable, "-c", ROADRUNNER_SCRIPT],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"roadrunner failed:\n{completed.stderr}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError(
            f"roadrunner returned no JSON:\n{completed.stdout}\n{completed.stderr}"
        ) from err
    return np.asarray(result)[:, 1:]
