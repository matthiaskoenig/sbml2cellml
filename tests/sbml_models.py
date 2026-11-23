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


def small_compartment_model(size: float = 1e-13, mid: str = "small") -> libsbml.Model:
    """`A` decays with `k * A * c` in a compartment of `size` litre.

    The concentration of `A` is 1, so its amount is `size`: the state of the
    solver is far below the usual absolute tolerance.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId(mid)
    c: libsbml.Compartment = model.createCompartment()
    c.setId("c")
    c.setSize(size)
    c.setConstant(True)
    s: libsbml.Species = model.createSpecies()
    s.setId("A")
    s.setCompartment("c")
    s.setInitialConcentration(1.0)
    s.setHasOnlySubstanceUnits(False)
    s.setBoundaryCondition(False)
    s.setConstant(False)
    p: libsbml.Parameter = model.createParameter()
    p.setId("k")
    p.setValue(1.0)
    p.setConstant(True)
    r: libsbml.Reaction = model.createReaction()
    r.setId("decay")
    r.setReversible(False)
    reactant: libsbml.SpeciesReference = r.createReactant()
    reactant.setSpecies("A")
    reactant.setConstant(True)
    reactant.setStoichiometry(1.0)
    klaw: libsbml.KineticLaw = r.createKineticLaw()
    klaw.setMath(libsbml.parseL3Formula("k * A * c"))
    _SBML_DOCUMENTS.append(doc)
    return model


def event_model(mid: str = "events") -> libsbml.Model:
    """`simple_model` with the event `time > 10` which sets `k1` to 2."""
    model = simple_model(mid)
    event: libsbml.Event = model.createEvent()
    event.setId("e1")
    event.setUseValuesFromTriggerTime(True)
    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setMath(libsbml.parseL3Formula("time > 10"))
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    assignment: libsbml.EventAssignment = event.createEventAssignment()
    assignment.setVariable("k1")
    assignment.setMath(libsbml.parseL3Formula("2.0"))
    return model


def time_id_model(mid: str = "timeid") -> libsbml.Model:
    """`simple_model` with a parameter called `time` in its kinetic law.

    The variable of integration of the CellML model cannot be called `time`
    then, the parameter has that name.
    """
    model = simple_model(mid)
    p: libsbml.Parameter = model.createParameter()
    p.setId("time")
    p.setValue(2.0)
    p.setConstant(True)
    klaw = model.getReaction("r1").getKineticLaw()
    klaw.setMath(libsbml.parseL3Formula("k1 * S1 * time"))
    return model


def analytic_time_model(mid: str = "analytic") -> libsbml.Model:
    """`A = 2 * time`: an assignment rule of time without a rate equation."""
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId(mid)
    p: libsbml.Parameter = model.createParameter()
    p.setId("A")
    p.setConstant(False)
    rule: libsbml.AssignmentRule = model.createAssignmentRule()
    rule.setVariable("A")
    rule.setMath(libsbml.parseL3Formula("2 * time"))
    _SBML_DOCUMENTS.append(doc)
    return model


def small_state_model(value: float = 1e-6, mid: str = "smallstate") -> libsbml.Model:
    """`A` decays with `k * A * c` from the concentration `value`.

    The compartment has the size 1, so the concentration of `A` is its
    amount and the state of a CellML conversion of the model is `value`:
    far below the usual absolute tolerance.
    """
    model = small_compartment_model(size=1.0, mid=mid)
    model.getSpecies("A").setInitialConcentration(value)
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


XHTML = "http://www.w3.org/1999/xhtml"


def cv_term(qualifier: int, *resources: str, model: bool = False) -> libsbml.CVTerm:
    term = libsbml.CVTerm()
    if model:
        term.setQualifierType(libsbml.MODEL_QUALIFIER)
        term.setModelQualifierType(qualifier)
    else:
        term.setQualifierType(libsbml.BIOLOGICAL_QUALIFIER)
        term.setBiologicalQualifierType(qualifier)
    for resource in resources:
        term.addResource(resource)
    return term


def annotated_species(model: libsbml.Model) -> libsbml.Species:
    """S1 with a name, notes, an SBO term and two CV terms."""
    species: libsbml.Species = model.getSpecies("S1")
    species.setMetaId("meta_S1")
    species.setName("glucose & co")
    species.setNotes(f'<body xmlns="{XHTML}"><p>The <b>substrate</b>.</p></body>')
    species.setSBOTerm("SBO:0000247")
    species.addCVTerm(cv_term(libsbml.BQB_IS, "https://identifiers.org/CHEBI:17234"))
    species.addCVTerm(
        cv_term(
            libsbml.BQB_IS_VERSION_OF,
            "https://identifiers.org/CHEBI:4167",
            "https://identifiers.org/kegg.compound/C00031",
        )
    )
    return species


def with_history(model: libsbml.Model) -> None:
    model.setMetaId("meta_model")
    history = libsbml.ModelHistory()
    creator = libsbml.ModelCreator()
    creator.setFamilyName("König")
    creator.setGivenName("Matthias")
    creator.setEmail("koenigmx@hu-berlin.de")
    creator.setOrganization("Humboldt-University Berlin")
    history.addCreator(creator)
    history.setCreatedDate(libsbml.Date("2026-09-19T12:00:00Z"))
    history.addModifiedDate(libsbml.Date("2026-09-19T13:00:00Z"))
    assert model.setModelHistory(history) == libsbml.LIBSBML_OPERATION_SUCCESS
    model.addCVTerm(
        cv_term(
            libsbml.BQM_IS_DESCRIBED_BY, "https://doi.org/10.1038/35002125", model=True
        )
    )


def stoichiometry_math_model(mid: str = "stoichiometry_math") -> libsbml.Model:
    """SBML L2V4 model whose product has a `<stoichiometryMath>`.

    `S1 -> n S2` with `k1 * S1`, where the stoichiometry of the product is
    the formula `2 * f` of the parameters of the model. The reference has
    no id, as a reference of level 2 usually has none.
    """
    doc = libsbml.SBMLDocument(2, 4)
    model: libsbml.Model = doc.createModel()
    model.setId(mid)
    c: libsbml.Compartment = model.createCompartment()
    c.setId("cell")
    c.setSize(1.0)
    c.setConstant(True)
    for pid, value in (("k1", 0.5), ("f", 3.0)):
        p: libsbml.Parameter = model.createParameter()
        p.setId(pid)
        p.setValue(value)
        p.setConstant(True)
    for sid, value in (("S1", 10.0), ("S2", 0.0)):
        s: libsbml.Species = model.createSpecies()
        s.setId(sid)
        s.setCompartment("cell")
        s.setInitialConcentration(value)
        s.setHasOnlySubstanceUnits(False)
        s.setBoundaryCondition(False)
        s.setConstant(False)
    r: libsbml.Reaction = model.createReaction()
    r.setId("r1")
    r.setReversible(False)
    reactant: libsbml.SpeciesReference = r.createReactant()
    reactant.setSpecies("S1")
    reactant.setStoichiometry(1.0)
    product: libsbml.SpeciesReference = r.createProduct()
    product.setSpecies("S2")
    math: libsbml.StoichiometryMath = product.createStoichiometryMath()
    math.setMath(libsbml.parseL3Formula("2 * f"))
    klaw: libsbml.KineticLaw = r.createKineticLaw()
    klaw.setMath(libsbml.parseL3Formula("k1 * S1"))
    _SBML_DOCUMENTS.append(doc)
    return model


def quotient_model(mid: str = "quotient") -> libsbml.Model:
    """SBML L3V2 model whose parameters hold `quotient(-7, 3)` and `quotient(7, 3)`.

    The integer division of the MathML of SBML truncates towards zero, so
    the values are -2 and 2, where the floor of the division gives -3 and 2.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId(mid)
    for pid, value in (("a", -7.0), ("b", 3.0)):
        p: libsbml.Parameter = model.createParameter()
        p.setId(pid)
        p.setValue(value)
        p.setConstant(True)
    for pid, formula in (
        ("negative", "quotient(a, b)"),
        ("positive", "quotient(-a, b)"),
    ):
        p = model.createParameter()
        p.setId(pid)
        p.setConstant(False)
        rule: libsbml.AssignmentRule = model.createAssignmentRule()
        rule.setVariable(pid)
        rule.setMath(libsbml.parseL3Formula(formula))
    _SBML_DOCUMENTS.append(doc)
    return model
