"""Tests of the conversion of SBML units to CellML."""

from pathlib import Path

import libcellml
import libsbml
import pytest

from sbml2cellml import convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.cellml import model_to_string
from tests.sbml_models import annotated_model, simple_model, unit_definition, write_sbml


def convert(model: libsbml.Model, tmp_path: Path) -> libcellml.Model:
    return convert_sbml2cellml(write_sbml(tmp_path / "model.xml", model))


def variable_units(model: libcellml.Model) -> dict[str, str]:
    component = model.component(0)
    return {
        component.variable(k).name(): component.variable(k).units().name()
        for k in range(component.variableCount())
    }


def unit_attributes(model: libcellml.Model, name: str) -> list[tuple]:
    """`(reference, prefix, exponent, multiplier)` of the units."""
    units = model.units(name)
    return [tuple(units.unitAttributes(k)[:4]) for k in range(units.unitCount())]


def test_complete_annotation_gives_every_variable_its_units(tmp_path: Path) -> None:
    model = convert(annotated_model(), tmp_path)
    assert variable_units(model) == {
        "time": "min",
        "cell": "litre",
        "k1": "per_min",
        # a species is a concentration, substance per size of the compartment
        "S1": "mmole_per_litre",
        # unless it has only substance units
        "S2": "mmole",
        # the rate of the reaction, extent per time
        "r1": "mmole_per_min",
    }
    assert unit_attributes(model, "mmole") == [("mole", "milli", 1.0, 1.0)]
    assert unit_attributes(model, "min") == [("second", "", 1.0, 60.0)]
    assert unit_attributes(model, "mmole_per_litre") == [
        ("mmole", "", 1.0, 1.0),
        ("litre", "", -1.0, 1.0),
    ]


def test_amount_of_a_species_in_a_changing_compartment_has_substance_units(
    tmp_path: Path,
) -> None:
    model_sbml = annotated_model("growing")
    model_sbml.getCompartment("cell").setConstant(False)
    rule: libsbml.RateRule = model_sbml.createRateRule()
    rule.setVariable("cell")
    rule.setMath(libsbml.parseL3Formula("k1 * cell"))
    units = variable_units(convert(model_sbml, tmp_path))
    assert units["S1"] == "mmole_per_litre"
    assert units["S1_amount"] == "mmole"


def test_every_element_has_a_unique_id(tmp_path: Path) -> None:
    """External metadata points at the ids of the model, variables and units."""
    model_sbml = annotated_model()
    p: libsbml.Parameter = model_sbml.createParameter()
    p.setId("units_mmole")  # the id the units `mmole` would get
    p.setValue(1.0)
    p.setConstant(True)
    p.setUnits("dimensionless")
    model = convert(model_sbml, tmp_path)
    component = model.component(0)
    variable_ids = {
        component.variable(k).name(): component.variable(k).id()
        for k in range(component.variableCount())
    }
    assert all(name == vid for name, vid in variable_ids.items())
    units_ids = {
        model.units(k).name(): model.units(k).id() for k in range(model.unitsCount())
    }
    assert units_ids["min"] == "units_min"
    assert units_ids["mmole"] == "units_mmole_2"
    assert model.id() == "annotated"
    ids = [*variable_ids.values(), *units_ids.values(), model.id()]
    assert len(set(ids)) == len(ids)


def test_multiplier_is_outside_of_the_exponent(tmp_path: Path) -> None:
    """SBML `(60 * second)^-1` is CellML `1/60 * second^-1`."""
    model = convert(annotated_model(), tmp_path)
    ((reference, prefix, exponent, multiplier),) = unit_attributes(model, "per_min")
    assert (reference, prefix, exponent) == ("second", "", -1.0)
    assert multiplier == pytest.approx(1.0 / 60.0)


def test_existing_unit_definition_is_used_for_a_concentration(tmp_path: Path) -> None:
    sbml = annotated_model()
    unit_definition(
        sbml,
        "mM",
        (libsbml.UNIT_KIND_MOLE, 1.0, -3, 1.0),
        (libsbml.UNIT_KIND_LITRE, -1.0, 0, 1.0),
    )
    model = convert(sbml, tmp_path)
    assert variable_units(model)["S1"] == "mM"
    assert not model.hasUnits("mmole_per_litre")


def test_incomplete_annotation_keeps_the_variables_dimensionless(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sbml = annotated_model()
    sbml.getParameter("k1").unsetUnits()
    model = convert(sbml, tmp_path)
    assert set(variable_units(model).values()) == {"dimensionless"}
    # the unit definitions are converted nevertheless
    assert model.hasUnits("per_min")
    assert "unit annotation is incomplete: k1" in caplog.text


def test_model_without_units_logs_no_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model = convert(simple_model(), tmp_path)
    assert set(variable_units(model).values()) == {"dimensionless"}
    assert model.unitsCount() == 0
    assert "incomplete" not in caplog.text


def test_units_of_numbers(tmp_path: Path) -> None:
    sbml = annotated_model()
    p: libsbml.Parameter = sbml.createParameter()
    p.setId("p")
    p.setConstant(False)
    p.setUnits("item")
    rule: libsbml.AssignmentRule = sbml.createAssignmentRule()
    rule.setVariable("p")
    rule.setMath(libsbml.parseL3Formula("2 item + 3 avogadro * 1 dimensionless"))
    model = convert(sbml, tmp_path)
    text = model_to_string(model)
    assert '<cn cellml:units="item">2</cn>' in text
    assert '<cn cellml:units="avogadro">3</cn>' in text
    assert variable_units(model)["p"] == "item"
    # CellML has neither item nor avogadro: new base units and a number
    assert unit_attributes(model, "item") == []
    ((reference, _, exponent, multiplier),) = unit_attributes(model, "avogadro")
    assert (reference, exponent) == ("dimensionless", 1.0)
    assert multiplier == pytest.approx(6.02214179e23)


def test_units_of_numbers_in_a_model_without_annotation(tmp_path: Path) -> None:
    """The glimepiride intestine and body models failed with these."""
    sbml = simple_model()
    unit_definition(sbml, "per_min", (libsbml.UNIT_KIND_SECOND, -1.0, 0, 60.0))
    sbml.getReaction("r1").getKineticLaw().setMath(
        libsbml.parseL3Formula("k1 * S1 * 2 per_min")
    )
    model = convert(sbml, tmp_path)
    assert '<cn cellml:units="per_min">2</cn>' in model_to_string(model)


def test_reaction_rate_variable_is_extent_per_time(tmp_path: Path) -> None:
    sbml = annotated_model()
    p: libsbml.Parameter = sbml.createParameter()
    p.setId("flux")
    p.setConstant(False)
    p.setUnits("mmole_per_min")
    unit_definition(
        sbml,
        "mmole_per_min",
        (libsbml.UNIT_KIND_MOLE, 1.0, -3, 1.0),
        (libsbml.UNIT_KIND_SECOND, -1.0, 0, 60.0),
    )
    rule: libsbml.AssignmentRule = sbml.createAssignmentRule()
    rule.setVariable("flux")
    rule.setMath(libsbml.parseL3Formula("r1"))
    model = convert(sbml, tmp_path)
    assert variable_units(model)["r1"] == "mmole_per_min"


def test_species_reference_and_local_parameter_units(tmp_path: Path) -> None:
    sbml = annotated_model()
    reaction: libsbml.Reaction = sbml.getReaction("r1")
    reaction.getReactant(0).setId("S1_stoichiometry")
    local: libsbml.LocalParameter = reaction.getKineticLaw().createLocalParameter()
    local.setId("k")
    local.setValue(2.0)
    local.setUnits("per_min")
    reaction.getKineticLaw().setMath(libsbml.parseL3Formula("k * S1 * cell"))
    units = variable_units(convert(sbml, tmp_path))
    assert units["S1_stoichiometry"] == "dimensionless"
    assert units["r1_k"] == "per_min"


def test_level_2_builtin_units(tmp_path: Path) -> None:
    """Level 2 has the units `substance`, `time` and `volume` built in."""
    doc = libsbml.SBMLDocument(2, 4)
    sbml: libsbml.Model = doc.createModel()
    sbml.setId("level2")
    compartment: libsbml.Compartment = sbml.createCompartment()
    compartment.setId("cell")
    compartment.setSize(1.0)
    species: libsbml.Species = sbml.createSpecies()
    species.setId("S1")
    species.setCompartment("cell")
    species.setInitialConcentration(1.0)
    parameter: libsbml.Parameter = sbml.createParameter()
    parameter.setId("k")
    parameter.setValue(1.0)
    parameter.setUnits("dimensionless")
    rule: libsbml.RateRule = sbml.createRateRule()
    rule.setVariable("S1")
    rule.setMath(libsbml.parseL3Formula("-k * S1"))
    path = tmp_path / "level2.xml"
    libsbml.writeSBMLToFile(doc, str(path))
    model = convert_sbml2cellml(path)
    assert variable_units(model) == {
        "time": "second",
        "cell": "litre",
        "S1": "mole_per_litre",
        "k": "dimensionless",
    }


def test_unit_definition_id_which_is_no_cellml_identifier(tmp_path: Path) -> None:
    sbml = annotated_model()
    unit_definition(sbml, "_per_min", (libsbml.UNIT_KIND_SECOND, -1.0, 0, 60.0))
    sbml.getParameter("k1").setUnits("_per_min")
    model = convert(sbml, tmp_path)
    assert variable_units(model)["k1"] == "u_per_min"


def test_roundtrip_keeps_the_units(tmp_path: Path) -> None:
    sbml = annotated_model()
    cellml_path = tmp_path / "model.cellml"
    convert_sbml2cellml(write_sbml(tmp_path / "model.xml", sbml), cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    roundtrip: libsbml.Model = doc.getModel()
    assert roundtrip.getTimeUnits() == "min"
    for uid in ("mmole", "min", "per_min"):
        assert libsbml.UnitDefinition.areIdentical(
            sbml.getUnitDefinition(uid), roundtrip.getUnitDefinition(uid)
        ), uid
    assert roundtrip.getParameter("k1").getUnits() == "per_min"
    assert roundtrip.getParameter("S1").getUnits() == "mmole_per_litre"
    assert roundtrip.getParameter("cell").getUnits() == "litre"


def test_power_of_ten_multiplier_becomes_the_prefix(tmp_path: Path) -> None:
    """`(1000 gram)^-1` is `kilo gram ^-1`, the prefix is inside the exponent."""
    sbml = annotated_model()
    unit_definition(sbml, "per_kg", (libsbml.UNIT_KIND_GRAM, -1.0, 0, 1000.0))
    unit_definition(sbml, "mul", (libsbml.UNIT_KIND_LITRE, 1.0, -3, 0.001))
    model = convert(sbml, tmp_path)
    assert unit_attributes(model, "per_kg") == [("gram", "kilo", -1.0, 1.0)]
    assert unit_attributes(model, "mul") == [("litre", "micro", 1.0, 1.0)]


def test_level_2_model_without_units_logs_no_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The built-in units alone are no annotation which could be incomplete."""
    doc = libsbml.SBMLDocument(2, 4)
    sbml: libsbml.Model = doc.createModel()
    sbml.setId("level2")
    compartment: libsbml.Compartment = sbml.createCompartment()
    compartment.setId("cell")
    compartment.setSize(1.0)
    parameter: libsbml.Parameter = sbml.createParameter()
    parameter.setId("k")
    parameter.setValue(1.0)
    path = tmp_path / "level2.xml"
    libsbml.writeSBMLToFile(doc, str(path))
    model = convert_sbml2cellml(path)
    assert set(variable_units(model).values()) == {"dimensionless"}
    assert "incomplete" not in caplog.text


def test_level_2_area_is_added_as_units(tmp_path: Path) -> None:
    doc = libsbml.SBMLDocument(2, 4)
    sbml: libsbml.Model = doc.createModel()
    sbml.setId("membrane")
    compartment: libsbml.Compartment = sbml.createCompartment()
    compartment.setId("membrane")
    compartment.setSpatialDimensions(2)
    compartment.setSize(1.0)
    path = tmp_path / "membrane.xml"
    libsbml.writeSBMLToFile(doc, str(path))
    model = convert_sbml2cellml(path)
    assert variable_units(model) == {"membrane": "area"}
    assert unit_attributes(model, "area") == [("metre", "", 2.0, 1.0)]
