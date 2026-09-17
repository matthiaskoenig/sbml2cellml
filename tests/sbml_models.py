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
