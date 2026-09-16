"""Convert the glimepiride models to CellML and simulate the liver model.

The models are the physiologically based pharmacokinetic models of
https://github.com/matthiaskoenig/glimepiride-model. The current converter
renders the liver and kidney models as valid CellML; the intestine and body
models hit known conversion gaps (units on numbers, function definitions), see
https://matthiaskoenig.github.io/sbml2cellml/roadmap/. Only the liver model
is fully constrained for libopencor.
"""

from pathlib import Path

from sbml2cellml import convert_sbml2cellml, log
from sbml2cellml.cellml import errors, format_issues, validate_model
from sbml2cellml.console import console
from sbml2cellml.simulate import plot_timecourse, run_timecourse

MODELS_DIR: Path = Path(__file__).parent / "models"
RESULTS_DIR: Path = Path(__file__).parent / "results"

MODEL_NAMES: list[str] = [
    "glimepiride_kidney",
    "glimepiride_liver",
    "glimepiride_intestine",
    "glimepiride_body",
    "glimepiride_body_flat",
]
#: models which libopencor can simulate
SIMULATED_MODELS: list[str] = ["glimepiride_liver"]


def convert_glimepiride_models(results_dir: Path) -> dict[str, Path]:
    """Convert every model into `results_dir` and report the validation.

    Returns:
        The CellML path of every model by name.
    """
    results_dir.mkdir(exist_ok=True)
    cellml_paths: dict[str, Path] = {}
    for name in MODEL_NAMES:
        console.rule(name, style="white")
        cellml_path = results_dir / f"{name}.cellml"
        model = convert_sbml2cellml(
            MODELS_DIR / f"{name}.xml", cellml_path=cellml_path, validate=False
        )
        issues = errors(validate_model(model))
        if issues:
            console.print(f"{len(issues)} errors:", style="error")
            console.print(format_issues(issues[:5]))
        else:
            console.print("valid CellML", style="success")
        cellml_paths[name] = cellml_path
    return cellml_paths


if __name__ == "__main__":
    log.enable_rich_logging()
    paths = convert_glimepiride_models(RESULTS_DIR)
    for name in SIMULATED_MODELS:
        console.rule(f"simulate {name}", style="white")
        df, units = run_timecourse(paths[name], start=0.0, end=100.0, steps=100)
        console.print(df)
        plot_timecourse(df=df, units=units)
