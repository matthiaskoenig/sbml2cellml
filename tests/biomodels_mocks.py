"""Shared BioModels mocks for the runner and CLI tests.

`model_info` and `download_model` are monkeypatched to serve local files
instead of the network: `BIOMD_A` resolves to the glimepiride liver model
(no SBML packages), `BIOMD_B` to a tiny synthetic model using the `comp`
package, any other id raises `BioModelsError`.
"""

from pathlib import Path

import pytest

from sbml2cellml.biomodels.models import BioModelsError, ModelInfo
from tests.conftest import MODELS_DIR

#: model without SBML packages, used as `BIOMD_A`
LIVER_MODEL = MODELS_DIR / "glimepiride_liver.xml"
INFO_A = ModelInfo(
    id="BIOMD_A",
    name="Edelstein1996 - EPSP ACh event",
    publication_id="BIOMD_A",
    format_version="L3V1",
    main_file="model.xml",
)
#: metadata of the `comp` model, `BIOMD_B`
INFO_B = ModelInfo(
    id="BIOMD_B",
    name="Comp submodel",
    publication_id="BIOMD_B",
    format_version="L3V1",
    main_file="model.xml",
)


def write_comp_model(path: Path) -> Path:
    """Write a tiny SBML file declaring `comp` and using `comp:submodel`.

    The model has one species (so it is not skipped as `no species`) and one
    `comp:submodel` element, so `models.packages` reports it uses `comp`.

    Args:
        path: file to write.

    Returns:
        `path`.
    """
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
        'xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1" '
        'level="3" version="1"><model id="m">'
        '<listOfCompartments><compartment id="cell" size="1" constant="true"/>'
        "</listOfCompartments>"
        '<listOfSpecies><species id="S1" compartment="cell" '
        'initialConcentration="1" hasOnlySubstanceUnits="false" '
        'boundaryCondition="false" constant="false"/></listOfSpecies>'
        '<comp:submodel comp:id="s1" comp:modelRef="m2"/>'
        "</model></sbml>\n",
        encoding="utf-8",
    )
    return path


def mock_downloads(
    monkeypatch: pytest.MonkeyPatch, module: object, comp_path: Path
) -> None:
    """Monkeypatch `model_info` and `download_model` of `module`.

    Args:
        monkeypatch: the fixture of the calling test.
        module: module whose `model_info` and `download_model` names are
            replaced, e.g. `sbml2cellml.biomodels.runner`.
        comp_path: SBML file served for `BIOMD_B`.
    """

    def fake_model_info(model_id: str, cache: Path | None = None) -> ModelInfo:
        if model_id == "BIOMD_A":
            return INFO_A
        if model_id == "BIOMD_B":
            return INFO_B
        raise BioModelsError("boom")

    def fake_download_model(model_id: str, cache: Path | None = None) -> Path:
        if model_id == "BIOMD_A":
            return LIVER_MODEL
        if model_id == "BIOMD_B":
            return comp_path
        raise BioModelsError("boom")

    monkeypatch.setattr(module, "model_info", fake_model_info)
    monkeypatch.setattr(module, "download_model", fake_download_model)
