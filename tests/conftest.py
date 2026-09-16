"""Shared test configuration.

The example models are read from `examples/models/` instead of a second copy
in `tests/data/`; `tests/data/` only holds small fixtures created for a test.
"""

from pathlib import Path

#: models of the examples, also used as test fixtures
MODELS_DIR: Path = Path(__file__).parent.parent / "examples" / "models"
#: simple hand written CellML model (mass decay)
TEST_MODEL_PATH: Path = MODELS_DIR / "test_model.cellml"
#: names of the glimepiride SBML models, `<name>.xml` in `MODELS_DIR`
GLIMEPIRIDE_MODELS: list[str] = [
    "glimepiride_body",
    "glimepiride_body_flat",
    "glimepiride_intestine",
    "glimepiride_kidney",
    "glimepiride_liver",
]
