"""Tests of the BioModels case construction: constructs and settings."""

from pathlib import Path

import libsbml

from sbml2cellml.biomodels.cases import (
    ABSOLUTE,
    DURATION,
    RELATIVE,
    STEPS,
    biomodel_case,
    constructs,
)
from sbml2cellml.biomodels.models import ModelInfo
from sbml2cellml.testsuite.cases import skip_reason
from tests.conftest import MODELS_DIR
from tests.sbml_models import simple_model, write_sbml

LIVER_MODEL = MODELS_DIR / "glimepiride_liver.xml"
INFO = ModelInfo(
    id="BIOMD0000000001",
    name="Edelstein1996 - EPSP ACh event",
    publication_id="BIOMD0000000001",
    format_version="L2V4",
    main_file="BIOMD0000000001_url.xml",
)


def _read_model(path: Path) -> libsbml.Model:
    doc = libsbml.readSBMLFromFile(str(path))
    model = doc.getModel()
    assert model is not None
    return model


def test_constructs_liver() -> None:
    model = _read_model(LIVER_MODEL)
    text = LIVER_MODEL.read_text(encoding="utf-8")
    tags = constructs(model, text)
    print("liver constructs:", tags)
    assert "Reactions" in tags
    assert "Events" not in tags


def test_constructs_events(tmp_path: Path) -> None:
    model = simple_model("events")
    event: libsbml.Event = model.createEvent()
    event.setId("e1")
    event.setUseValuesFromTriggerTime(True)
    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setMath(libsbml.parseL3Formula("time > 10"))
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    ea: libsbml.EventAssignment = event.createEventAssignment()
    ea.setVariable("k1")
    ea.setMath(libsbml.parseL3Formula("1.0"))
    sbml_path = write_sbml(tmp_path / "events.xml", model)
    tags = constructs(model, sbml_path.read_text(encoding="utf-8"))
    assert "Events" in tags


def test_biomodel_case() -> None:
    model = _read_model(LIVER_MODEL)
    species_ids = tuple(s.getId() for s in model.getListOfSpecies())
    case = biomodel_case(INFO, LIVER_MODEL, ())
    assert case.id == INFO.id
    assert case.name == INFO.name
    assert case.sbml_path == LIVER_MODEL
    assert case.case_dir == LIVER_MODEL.parent
    assert case.expected is None
    assert case.test_tags == ()
    assert case.test_type == "TimeCourse"
    assert case.settings.start == 0.0
    assert case.settings.duration == DURATION
    assert case.settings.steps == STEPS
    assert case.settings.variables == species_ids
    assert case.settings.absolute == ABSOLUTE
    assert case.settings.relative == RELATIVE
    assert case.settings.amount == frozenset()
    assert case.settings.concentration == frozenset(species_ids)
    assert case.component_tags == constructs(
        model, LIVER_MODEL.read_text(encoding="utf-8")
    )

    case_with_package = biomodel_case(INFO, LIVER_MODEL, ("comp",))
    assert "comp:package" in case_with_package.component_tags
    assert skip_reason(case_with_package) == "package comp"
