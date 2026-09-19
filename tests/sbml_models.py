"""Hand built SBML models shared by several test modules."""

from pathlib import Path

import libsbml

#: libsbml frees a model when its document is garbage collected; keep every
#: document created by `simple_model` alive for the life of the process.
_SBML_DOCUMENTS: list[libsbml.SBMLDocument] = []


def write_sbml(path: Path, model: libsbml.Model) -> Path:
    """Write the document of a model."""
    doc = model.getSBMLDocument()
    libsbml.writeSBMLToFile(doc, str(path))
    return path


def simple_model(mid: str = "simple") -> libsbml.Model:
    """SBML L3V2 model with one compartment, one parameter and two species.

    S1 is in concentration, S2 in amount, one reaction S1 -> S2 with `k1 * S1`.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId(mid)
    c: libsbml.Compartment = model.createCompartment()
    c.setId("cell")
    c.setSize(2.0)
    c.setConstant(True)
    p: libsbml.Parameter = model.createParameter()
    p.setId("k1")
    p.setValue(0.5)
    p.setConstant(True)
    s1: libsbml.Species = model.createSpecies()
    s1.setId("S1")
    s1.setCompartment("cell")
    s1.setInitialConcentration(10.0)
    s1.setHasOnlySubstanceUnits(False)
    s1.setBoundaryCondition(False)
    s1.setConstant(False)
    s2: libsbml.Species = model.createSpecies()
    s2.setId("S2")
    s2.setCompartment("cell")
    s2.setInitialAmount(4.0)
    s2.setHasOnlySubstanceUnits(True)
    s2.setBoundaryCondition(False)
    s2.setConstant(False)
    r: libsbml.Reaction = model.createReaction()
    r.setId("r1")
    r.setReversible(False)
    reactant: libsbml.SpeciesReference = r.createReactant()
    reactant.setSpecies("S1")
    reactant.setConstant(True)
    reactant.setStoichiometry(1.0)
    product: libsbml.SpeciesReference = r.createProduct()
    product.setSpecies("S2")
    product.setConstant(True)
    product.setStoichiometry(1.0)
    klaw: libsbml.KineticLaw = r.createKineticLaw()
    klaw.setMath(libsbml.parseL3Formula("k1 * S1"))
    _SBML_DOCUMENTS.append(doc)
    return model


def growing_compartment_model(mid: str = "growing") -> libsbml.Model:
    """`simple_model` whose compartment grows: `d cell / d time = 0.5 * cell`."""
    model = simple_model(mid)
    model.getCompartment("cell").setConstant(False)
    rule: libsbml.RateRule = model.createRateRule()
    rule.setVariable("cell")
    rule.setMath(libsbml.parseL3Formula("0.5 * cell"))
    return model


def symbol_ids_model(mid: str = "symbol_ids") -> libsbml.Model:
    """`simple_model` whose ids are symbols of the formula syntax of libsbml.

    The compartment is `pi`, the species S1 `NaN` and the parameter `avogadro`
    (2.0) is a factor of the kinetic law `k1 * NaN * avogadro`. The formula is
    parsed with the model, which makes its ids names and not symbols.
    """
    model = simple_model(mid)
    model.getCompartment("cell").setId("pi")
    model.getSpecies("S1").setId("NaN")
    for species in model.getListOfSpecies():
        species.setCompartment("pi")
    model.getReaction("r1").getReactant(0).setSpecies("NaN")
    p: libsbml.Parameter = model.createParameter()
    p.setId("avogadro")
    p.setValue(2.0)
    p.setConstant(True)
    klaw: libsbml.KineticLaw = model.getReaction("r1").getKineticLaw()
    klaw.setMath(libsbml.parseL3FormulaWithModel("k1 * NaN * avogadro", model))
    return model


def unit_definition(
    model: libsbml.Model, uid: str, *units: tuple[int, float, int, float]
) -> libsbml.UnitDefinition:
    """Add a unit definition from `(kind, exponent, scale, multiplier)` units."""
    definition: libsbml.UnitDefinition = model.createUnitDefinition()
    definition.setId(uid)
    for kind, exponent, scale, multiplier in units:
        unit: libsbml.Unit = definition.createUnit()
        unit.setKind(kind)
        unit.setExponent(exponent)
        unit.setScale(scale)
        unit.setMultiplier(multiplier)
    return definition


def annotated_model(mid: str = "annotated") -> libsbml.Model:
    """`simple_model` with a complete unit annotation.

    Substance and extent in `mmole`, time in `min`, volume in `litre`
    (model units), `k1` in `per_min`.
    """
    model = simple_model(mid)
    unit_definition(model, "mmole", (libsbml.UNIT_KIND_MOLE, 1.0, -3, 1.0))
    unit_definition(model, "min", (libsbml.UNIT_KIND_SECOND, 1.0, 0, 60.0))
    unit_definition(model, "per_min", (libsbml.UNIT_KIND_SECOND, -1.0, 0, 60.0))
    model.setSubstanceUnits("mmole")
    model.setExtentUnits("mmole")
    model.setTimeUnits("min")
    model.setVolumeUnits("litre")
    # without the dimensions the units of the model do not apply
    model.getCompartment("cell").setSpatialDimensions(3.0)
    model.getParameter("k1").setUnits("per_min")
    return model


def delay_model(mid: str = "delayed") -> libsbml.Model:
    """`simple_model` with the delay symbol in the kinetic law.

    CellML has no delays: the model is a known conversion gap, its CellML
    is not valid.
    """
    model = simple_model(mid)
    klaw: libsbml.KineticLaw = model.getReaction("r1").getKineticLaw()
    klaw.setMath(libsbml.parseL3Formula("k1 * delay(S1, 1)"))
    return model
