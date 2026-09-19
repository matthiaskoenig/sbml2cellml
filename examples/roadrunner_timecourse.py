"""Timecourse of an SBML model with roadrunner, written as CSV.

roadrunner and libopencor bundle different LLVM versions and crash once both
have compiled a model in the same process, so the roadrunner simulations of
the examples run this script in a process of their own:

    python roadrunner_timecourse.py model.xml result.csv --end 600 --steps 600 PX PY PZ
"""

import argparse
from pathlib import Path

import pandas as pd
import roadrunner


def timecourse(
    sbml_path: Path, selections: list[str], end: float, steps: int
) -> pd.DataFrame:
    """Simulate from 0 to `end` and return `time` and the selections as columns."""
    rr = roadrunner.RoadRunner(str(sbml_path))
    rr.timeCourseSelections = ["time", *selections]
    result = rr.simulate(0.0, end, steps=steps)
    return pd.DataFrame(result, columns=result.colnames)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbml", type=Path, help="SBML file")
    parser.add_argument("csv", type=Path, help="CSV file of the result")
    parser.add_argument("selections", nargs="+", help="ids of the columns")
    parser.add_argument("--end", type=float, default=100.0, help="end time")
    parser.add_argument("--steps", type=int, default=100, help="number of steps")
    args = parser.parse_args()
    df = timecourse(args.sbml, args.selections, end=args.end, steps=args.steps)
    df.to_csv(args.csv, index=False)
