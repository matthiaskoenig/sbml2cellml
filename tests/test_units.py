"""Tests of the conversion of CellML units to SBML unit definitions."""

import libcellml
import libsbml
import pytest

from sbml2cellml.sbml import validate_document
from sbml2cellml.units import (
    BaseUnit,
    UnitsConversionError,
    add_units,
    expand_units,
    prefix_scale,
    unit_id,
)


def model_with_units() -> libcellml.Model:
    model = libcellml.Model("units")
    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1.0)
    mM = libcellml.Units("mM")
    mM.addUnit("mole", "milli")
    mM.addUnit("litre", "", -1.0)
    mM_per_min = libcellml.Units("mM_per_min")  # custom referencing custom
    mM_per_min.addUnit("mM")
    mM_per_min.addUnit("second", "", -1.0, 1.0 / 60.0)
    kmM2 = libcellml.Units("kmM2")  # prefix and multiplier on a custom reference
    kmM2.addUnit("mM", "kilo", 2.0, 3.0)
    percent = libcellml.Units("percent")
    percent.addUnit("dimensionless", "", 1.0, 0.01)
    empty = libcellml.Units("nothing")
    for units in [per_second, mM, mM_per_min, kmM2, percent, empty]:
        model.addUnits(units)
    return model


@pytest.mark.parametrize(
    ("prefix", "scale"),
    [("", 0), ("milli", -3), ("kilo", 3), ("micro", -6), ("-5", -5), ("2", 2)],
)
def test_prefix_scale(prefix: str, scale: int) -> None:
    assert prefix_scale(prefix) == scale


def test_prefix_scale_invalid() -> None:
    with pytest.raises(UnitsConversionError):
        prefix_scale("huge")


def test_expand_standard_reference() -> None:
    model = model_with_units()
    assert expand_units(model.units("per_second"), model) == [
        BaseUnit(libsbml.UNIT_KIND_SECOND, -1.0, 0, 1.0)
    ]
    assert expand_units(model.units("mM"), model) == [
        BaseUnit(libsbml.UNIT_KIND_MOLE, 1.0, -3, 1.0),
        BaseUnit(libsbml.UNIT_KIND_LITRE, -1.0, 0, 1.0),
    ]


def test_expand_custom_reference() -> None:
    model = model_with_units()
    assert expand_units(model.units("mM_per_min"), model) == [
        BaseUnit(libsbml.UNIT_KIND_MOLE, 1.0, -3, 1.0),
        BaseUnit(libsbml.UNIT_KIND_LITRE, -1.0, 0, 1.0),
        BaseUnit(libsbml.UNIT_KIND_SECOND, -1.0, 0, pytest.approx(1.0 / 60.0)),  # ty: ignore[invalid-argument-type]
    ]
    # (3 * 10^3 * mM)^2 = (3000^(1/1) * mole 10^-3)^2 * litre^-2
    assert expand_units(model.units("kmM2"), model) == [
        BaseUnit(libsbml.UNIT_KIND_MOLE, 2.0, -3, pytest.approx(3000.0)),  # ty: ignore[invalid-argument-type]
        BaseUnit(libsbml.UNIT_KIND_LITRE, -2.0, 0, 1.0),
    ]


def test_expand_dimensionless_and_empty() -> None:
    model = model_with_units()
    assert expand_units(model.units("percent"), model) == [
        BaseUnit(libsbml.UNIT_KIND_DIMENSIONLESS, 1.0, 0, 0.01)
    ]
    assert expand_units(model.units("nothing"), model) == []


def test_expand_unknown_reference_raises() -> None:
    model = libcellml.Model("bad")
    units = libcellml.Units("bad")
    units.addUnit("furlong")
    model.addUnits(units)
    with pytest.raises(UnitsConversionError, match="furlong"):
        expand_units(units, model)


def test_expand_empty_custom_reference_keeps_factor() -> None:
    model = libcellml.Model("outer_empty")
    empty = libcellml.Units("nothing")
    outer = libcellml.Units("outer")
    outer.addUnit("nothing", "kilo", 2.0, 5.0)
    model.addUnits(empty)
    model.addUnits(outer)
    assert expand_units(outer, model) == [
        BaseUnit(libsbml.UNIT_KIND_DIMENSIONLESS, 2.0, 3, 5.0)
    ]


def test_gram_is_a_unit_kind() -> None:
    model = libcellml.Model("grams")
    mg = libcellml.Units("mg")
    mg.addUnit("gram", "milli")
    model.addUnits(mg)
    assert expand_units(mg, model) == [BaseUnit(libsbml.UNIT_KIND_GRAM, 1.0, -3, 1.0)]


def test_expand_zero_exponent_first_unit_raises() -> None:
    model = libcellml.Model("zero_exponent")
    zero = libcellml.Units("zero")
    zero.addUnit("second", 0.0)
    outer = libcellml.Units("outer")
    outer.addUnit("zero", "kilo", 1.0, 5.0)
    model.addUnits(zero)
    model.addUnits(outer)
    with pytest.raises(UnitsConversionError):
        expand_units(outer, model)


def test_add_units() -> None:
    model = model_with_units()
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml = doc.createModel()
    model_sbml.setId("units")
    ids = add_units(model, model_sbml)
    assert ids == {
        "per_second": "per_second",
        "mM": "mM",
        "mM_per_min": "mM_per_min",
        "kmM2": "kmM2",
        "percent": "percent",
        "nothing": "nothing",
    }
    assert model_sbml.getNumUnitDefinitions() == 6
    mM = model_sbml.getUnitDefinition("mM")
    assert mM.getNumUnits() == 2
    assert mM.getUnit(0).getKind() == libsbml.UNIT_KIND_MOLE
    assert mM.getUnit(0).getScale() == -3
    nothing = model_sbml.getUnitDefinition("nothing")
    assert nothing.getNumUnits() == 1
    assert nothing.getUnit(0).getKind() == libsbml.UNIT_KIND_DIMENSIONLESS
    assert validate_document(doc) == []
    # standard units are used by name
    assert unit_id("second", ids) == "second"
    assert unit_id("mM", ids) == "mM"


def test_add_units_avoids_predefined_unit_names() -> None:
    """Custom units named like a predefined SBML unit kind (`item`, ...) must
    not get that name as its definition id: libsbml rejects it."""
    model = libcellml.Model("items")
    item = libcellml.Units("item")
    item.addUnit("mole", "milli")
    model.addUnits(item)
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml = doc.createModel()
    model_sbml.setId("items")
    ids = add_units(model, model_sbml)
    assert ids == {"item": "item_2"}
    assert validate_document(doc) == []


def test_add_units_dedupes_colliding_ids() -> None:
    model = libcellml.Model("colliding")
    slash = libcellml.Units("mM/s")
    slash.addUnit("mole", "milli")
    underscore = libcellml.Units("mM_s")
    underscore.addUnit("mole", "milli")
    model.addUnits(slash)
    model.addUnits(underscore)
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml = doc.createModel()
    model_sbml.setId("colliding")
    ids = add_units(model, model_sbml)
    assert ids == {"mM/s": "mM_s", "mM_s": "mM_s_2"}
    assert model_sbml.getNumUnitDefinitions() == 2
    assert validate_document(doc) == []
