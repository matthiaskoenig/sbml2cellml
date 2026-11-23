"""Tests of the models of the online simulator of the documentation."""

import json
from pathlib import Path

import libcellml
import libsbml
import pytest

from sbml2cellml import rust
from sbml2cellml.cellml import cellml_version
from sbml2cellml.overview.checks import load_runs, works
from sbml2cellml.variables import components
from scripts.build_simulator_models import CHOICES, SERIES, SLIDERS

REPOSITORY = Path(__file__).parent.parent
DOCS = REPOSITORY / "docs"
MANIFEST = DOCS / "simulator" / "models.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def models(manifest: dict) -> list[dict]:
    return manifest["models"]


def test_manifest_is_the_selection_of_the_build_script(models: list[dict]) -> None:
    assert [model["id"] for model in models] == [choice.id for choice in CHOICES]
    assert models[0]["id"] == "BIOMD0000000012", "the page opens with the repressilator"


def test_every_model_is_a_file_of_the_documentation(models: list[dict]) -> None:
    for model in models:
        path = DOCS / model["file"]
        assert path.is_file(), model["file"]
        assert path.stat().st_size > 0


def test_every_model_passes_its_check(models: list[dict]) -> None:
    runs = {run.check.name: run for run in load_runs()}
    checks = {choice.id: choice.check for choice in CHOICES}
    for model in models:
        run = runs[checks[model["id"]]]
        assert works(run, model["id"]), f"{model['id']} does not pass its check"


def test_the_sliders_and_the_series_are_bounded(models: list[dict]) -> None:
    for model in models:
        assert 0 < len(model["parameters"]) <= SLIDERS
        assert 0 < len(model["series"]) <= SERIES
        labels = [series["label"] for series in model["series"]]
        assert len(set(labels)) == len(labels), f"{model['id']} repeats a label"
        for parameter in model["parameters"]:
            assert parameter["minimum"] <= parameter["value"] <= parameter["maximum"]
            assert parameter["step"] > 0
        assert model["timecourse"]["end"] > 0
        assert model["timecourse"]["steps"] > 0


def test_every_slider_and_series_is_in_both_documents(models: list[dict]) -> None:
    """The page sets a parameter in both models and plots a state of both.

    The documents are the ones the page holds: the published model and the
    conversion of it, which the WebAssembly module of the same rust
    converter writes in the browser.
    """
    for model in models:
        text = (DOCS / model["file"]).read_text(encoding="utf-8")
        if model["direction"] == "sbml2cellml":
            sbml = text
            cellml, _, _ = rust.convert_sbml_to_cellml(text, name=model["id"])
        else:
            cellml = text
            sbml, _, _ = rust.convert_cellml_to_sbml(text)
        document = libsbml.readSBMLFromString(sbml)
        sbml_model = document.getModel()
        # a document of CellML 1.0 or 1.1 is read in the permissive mode,
        # which is how the package and libopencor read it
        parser = libcellml.Parser(cellml_version(cellml) is None)
        parsed = parser.parseModel(cellml)
        # the components of a model are nested, an encapsulated component
        # is a component of its parent
        variables = {
            (component.name(), component.variable(k).name())
            for component in components(parsed)
            for k in range(component.variableCount())
        }
        for parameter in model["parameters"]:
            assert sbml_model.getParameter(parameter["sbml"]) is not None, (
                f"{model['id']}: no parameter {parameter['sbml']}"
            )
            key = (parameter["component"], parameter["variable"])
            assert key in variables, f"{model['id']}: no variable {key}"
        for series in model["series"]:
            component, name = series["cellml"].split("/", 1)
            assert (component, name) in variables, f"{model['id']}: {series['cellml']}"
            selection = series["sbml"].strip("[]")
            assert (
                sbml_model.getParameter(selection) is not None
                or sbml_model.getSpecies(selection) is not None
            ), f"{model['id']}: no selection {series['sbml']}"


def test_the_page_holds_the_simulator() -> None:
    index = (DOCS / "index.md").read_text(encoding="utf-8")
    assert "## Online simulator" in index
    assert 'data-models="simulator/models.json"' in index
    assert 'data-module="converter/sbml2cellml.wasm"' in index
    scripts = (REPOSITORY / "zensical.toml").read_text(encoding="utf-8")
    for name in ("wasm.js", "simulator.js"):
        assert f'"javascripts/{name}"' in scripts
    assert '"index.html#online-simulator"' in scripts
