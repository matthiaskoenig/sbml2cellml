"""Conversion of SBML units to CellML units.

Every unit definition of an SBML model becomes CellML units of the same name.
An SBML unit stands for `(multiplier * 10^scale * kind)^exponent`, a CellML
unit for `multiplier * (10^prefix * reference)^exponent`: the scale becomes
the prefix, together with a multiplier which is a power of ten, and any other
multiplier its power `multiplier^exponent`. The unit kinds
of SBML are the standard units of CellML, except for `item`, which becomes
new base units (units without a unit), and `avogadro`, which becomes the
dimensionless units of that number.

`CellMLUnits` also finds the units of the elements which become variables. A
compartment, a parameter and a species with only substance units reference
their units (a unit definition, a unit kind or the units of the model), a
species in concentration has the units of its substance per the units of its
compartment and the rate of a reaction the units of the extent per the units
of time. For such a quotient the unit definition of the model which is
identical to it is used, else units `numerator_per_denominator` are added.
"""

import logging
import math

import libcellml
import libsbml

from sbml2cellml.units import ITEM, PREFIXES
from sbml2cellml.variables import unique_sid

logger = logging.getLogger(__name__)

#: units of a quantity without units
DIMENSIONLESS = "dimensionless"
#: SBML unit kind without CellML counterpart: dimensionless units of its value
AVOGADRO = "avogadro"
#: the units which CellML has built in, all of them unit kinds of SBML
STANDARD_UNITS = frozenset(
    {
        "ampere",
        "becquerel",
        "candela",
        "coulomb",
        "dimensionless",
        "farad",
        "gram",
        "gray",
        "henry",
        "hertz",
        "joule",
        "katal",
        "kelvin",
        "kilogram",
        "litre",
        "lumen",
        "lux",
        "metre",
        "mole",
        "newton",
        "ohm",
        "pascal",
        "radian",
        "second",
        "siemens",
        "sievert",
        "steradian",
        "tesla",
        "volt",
        "watt",
        "weber",
    }
)
#: CellML prefix name by scale
PREFIX_NAMES: dict[int, str] = {scale: name for name, scale in PREFIXES.items()}
#: units which SBML level 1 and 2 have built in, as `(kind, exponent)`
BUILTIN_UNITS: dict[str, tuple[int, float]] = {
    "substance": (libsbml.UNIT_KIND_MOLE, 1.0),
    "time": (libsbml.UNIT_KIND_SECOND, 1.0),
    "volume": (libsbml.UNIT_KIND_LITRE, 1.0),
    "area": (libsbml.UNIT_KIND_METRE, 2.0),
    "length": (libsbml.UNIT_KIND_METRE, 1.0),
}
#: spellings of unit kinds which only SBML level 1 and 2 have
KIND_SPELLINGS = {"liter": "litre", "meter": "metre"}
#: size units of the model by the spatial dimensions of a compartment
_SIZE_UNITS = {3: "volume", 2: "area", 1: "length"}


def _round(value: float) -> float:
    """A float without the noise of a power, `0.010000000000000002` is `0.01`."""
    return float(f"{value:.15g}")


def _power_of_ten(scale: int, multiplier: float) -> tuple[int, float]:
    """Move a multiplier which is a power of ten into the scale.

    `(1000 gram)` is `kilo gram`: a prefix reads better than a multiplier and,
    other than the multiplier, is inside of the exponent in CellML as well.

    Returns:
        The scale and the multiplier which is left.
    """
    if multiplier > 0:
        power = round(math.log10(multiplier))
        if math.isclose(multiplier, 10.0**power, rel_tol=1e-12):
            return scale + power, 1.0
    return scale, multiplier


class CellMLUnits:
    """The CellML units of an SBML model."""

    def __init__(self, model_sbml: libsbml.Model, model: libcellml.Model) -> None:
        """Convert the unit definitions of the SBML model.

        Args:
            model_sbml: the SBML model.
            model: the CellML model, which the units are added to.
        """
        self._sbml = model_sbml
        self._model = model
        #: CellML units name by SBML unit reference
        self._names: dict[str, str] = {}
        #: names which are taken: the standard units and the units of the model
        self._used: set[str] = set(STANDARD_UNITS)
        definition: libsbml.UnitDefinition
        for definition in model_sbml.getListOfUnitDefinitions():
            self._add_definition(definition)

    @property
    def is_annotated(self) -> bool:
        """Whether the SBML model says anything about units.

        The units which level 1 and 2 have built in do not count: a model
        without any unit of its own is not an incomplete annotation.
        """
        model = self._sbml
        elements = [
            *model.getListOfCompartments(),
            *model.getListOfParameters(),
        ]
        return bool(
            model.getNumUnitDefinitions()
            or (
                model.getLevel() >= 3
                and any(
                    (
                        model.isSetSubstanceUnits(),
                        model.isSetTimeUnits(),
                        model.isSetVolumeUnits(),
                        model.isSetAreaUnits(),
                        model.isSetLengthUnits(),
                        model.isSetExtentUnits(),
                    )
                )
            )
            or any(element.isSetUnits() for element in elements)
            or any(
                species.isSetSubstanceUnits() for species in model.getListOfSpecies()
            )
        )

    def _unique(self, name: str) -> str:
        """A CellML identifier which no other units have."""
        if not name[:1].isalpha():
            # an SBML id may start with an underscore
            name = f"u{name}"
        return unique_sid(name, self._used)

    def _add_definition(self, definition: libsbml.UnitDefinition) -> None:
        """Add the CellML units of a unit definition."""
        uid: str = definition.getId()
        units = libcellml.Units(self._unique(uid))
        unit: libsbml.Unit
        for unit in definition.getListOfUnits():
            kind: int = unit.getKind()
            reference = self._kind(kind)
            if reference is None:
                logger.warning(
                    "Unit of kind '%s' in unit definition '%s' not converted, "
                    "CellML does not have it.",
                    libsbml.UnitKind_toString(kind),
                    uid,
                )
                continue
            exponent: float = unit.getExponentAsDouble()
            scale, base_multiplier = _power_of_ten(
                unit.getScale(), unit.getMultiplier()
            )
            multiplier = _round(base_multiplier**exponent)
            units.addUnit(
                reference, PREFIX_NAMES.get(scale, scale), exponent, multiplier
            )
        self._model.addUnits(units)
        self._names[uid] = units.name()
        logger.info("'%s' units for unit definition '%s'", units.name(), uid)

    def _kind(self, kind: int) -> str | None:
        """CellML units of an SBML unit kind, added when CellML lacks them."""
        name: str = libsbml.UnitKind_toString(kind)
        name = KIND_SPELLINGS.get(name, name)
        if name in (ITEM, AVOGADRO):
            if name not in self._names:
                units = libcellml.Units(self._unique(name))
                if name == AVOGADRO:
                    number = libsbml.ASTNode(libsbml.AST_NAME_AVOGADRO)
                    units.addUnit(DIMENSIONLESS, 0, 1.0, number.getReal())
                self._model.addUnits(units)
                self._names[name] = units.name()
            return self._names[name]
        # not e.g. celsius of SBML level 2 version 1
        return name if name in STANDARD_UNITS else None

    def name(self, reference: str) -> str | None:
        """CellML units of an SBML unit reference.

        Args:
            reference: the id of a unit definition, the name of a unit kind
                or units which the SBML level has built in (`substance`).

        Returns:
            The name of the CellML units, `None` for an unknown reference.
        """
        if not reference:
            return None
        if reference in self._names:
            return self._names[reference]
        kind = libsbml.UnitKind_forName(reference)
        if kind != libsbml.UNIT_KIND_INVALID:
            return self._kind(kind)
        if self._sbml.getLevel() < 3 and reference in BUILTIN_UNITS:
            kind, exponent = BUILTIN_UNITS[reference]
            base: str = libsbml.UnitKind_toString(kind)
            if exponent == 1.0:
                return base
            units = libcellml.Units(self._unique(reference))
            units.addUnit(base, exponent)
            self._model.addUnits(units)
            self._names[reference] = units.name()
            return units.name()
        return None

    def number_units(self, reference: str) -> str:
        """CellML units of the units of a number in a formula.

        Args:
            reference: the `sbml:units` of the number.

        Returns:
            The name of the CellML units, the reference itself when it is
            unknown (the validation of the CellML model reports it).
        """
        return self.name(reference) or reference

    def _definition(self, reference: str) -> libsbml.UnitDefinition | None:
        """The unit definition of an SBML unit reference, built when needed."""
        definition: libsbml.UnitDefinition | None = self._sbml.getUnitDefinition(
            reference
        )
        if definition is not None:
            return definition
        kind = libsbml.UnitKind_forName(reference)
        exponent = 1.0
        if kind == libsbml.UNIT_KIND_INVALID:
            if self._sbml.getLevel() >= 3 or reference not in BUILTIN_UNITS:
                return None
            kind, exponent = BUILTIN_UNITS[reference]
        definition = libsbml.UnitDefinition(3, 2)
        unit: libsbml.Unit = definition.createUnit()
        unit.setKind(kind)
        unit.setExponent(exponent)
        unit.setScale(0)
        unit.setMultiplier(1.0)
        return definition

    def per(self, numerator: str, denominator: str) -> str | None:
        """CellML units of the quotient of two SBML unit references.

        Args:
            numerator: SBML unit reference, e.g. the substance units.
            denominator: SBML unit reference, e.g. the units of a compartment.

        Returns:
            The name of the unit definition of the model which is identical
            to the quotient, else of the units
            `numerator_per_denominator`, which are added to the CellML model;
            `None` for an unknown reference.
        """
        key = f"{numerator}/{denominator}"
        if key in self._names:
            return self._names[key]
        names = self.name(numerator), self.name(denominator)
        definitions = self._definition(numerator), self._definition(denominator)
        if None in names or None in definitions:
            return None
        quotient = libsbml.UnitDefinition.divide(*definitions)
        candidate: libsbml.UnitDefinition
        for candidate in self._sbml.getListOfUnitDefinitions():
            if libsbml.UnitDefinition.areIdentical(quotient, candidate):
                self._names[key] = self._names[candidate.getId()]
                return self._names[key]
        units = libcellml.Units(self._unique(f"{names[0]}_per_{names[1]}"))
        units.addUnit(names[0])
        units.addUnit(names[1], -1.0)
        self._model.addUnits(units)
        self._names[key] = units.name()
        return units.name()

    def _model_units(self, quantity: str) -> str | None:
        """Reference of the units of the model for `substance`, `time`, ...

        SBML level 3 has attributes of the model for them, which may be
        unset, level 1 and 2 have the units built in (a unit definition of
        that id redefines them).
        """
        if self._sbml.getLevel() < 3:
            return quantity
        getter = {
            "substance": self._sbml.getSubstanceUnits,
            "time": self._sbml.getTimeUnits,
            "volume": self._sbml.getVolumeUnits,
            "area": self._sbml.getAreaUnits,
            "length": self._sbml.getLengthUnits,
            "extent": self._sbml.getExtentUnits,
        }[quantity]
        return getter() or None

    def _compartment_reference(self, compartment: libsbml.Compartment) -> str | None:
        """SBML unit reference of the size of a compartment."""
        if compartment.isSetUnits():
            return compartment.getUnits()
        dimensions = compartment.getSpatialDimensionsAsDouble()
        if self._sbml.getLevel() >= 3 and not compartment.isSetSpatialDimensions():
            return None
        if dimensions == 0:
            return DIMENSIONLESS
        quantity = _SIZE_UNITS.get(dimensions)
        return self._model_units(quantity) if quantity else None

    def time(self) -> str | None:
        """CellML units of time, `None` when the model does not set them."""
        reference = self._model_units("time")
        return self.name(reference) if reference else None

    def of_compartment(self, compartment: libsbml.Compartment) -> str | None:
        """CellML units of the size of a compartment, `None` when unknown."""
        reference = self._compartment_reference(compartment)
        return self.name(reference) if reference else None

    def of_parameter(
        self, parameter: libsbml.Parameter | libsbml.LocalParameter
    ) -> str | None:
        """CellML units of a parameter, `None` when it has none."""
        return self.name(parameter.getUnits()) if parameter.isSetUnits() else None

    def of_species(self, species: libsbml.Species) -> str | None:
        """CellML units of a species, `None` when unknown.

        The units of its substance when it has only substance units or its
        compartment no dimensions, else the concentration substance per
        size of the compartment.
        """
        substance = (
            species.getSubstanceUnits()
            if species.isSetSubstanceUnits()
            else self._model_units("substance")
        )
        if not substance:
            return None
        if species.getHasOnlySubstanceUnits():
            return self.name(substance)
        compartment = self._sbml.getCompartment(species.getCompartment())
        size = self._compartment_reference(compartment) if compartment else None
        if size is None:
            return None
        if size == DIMENSIONLESS:
            return self.name(substance)
        return self.per(substance, size)

    def of_reaction(self) -> str | None:
        """CellML units of the rate of a reaction: extent per time."""
        extent = self._model_units(
            "extent" if self._sbml.getLevel() >= 3 else "substance"
        )
        time = self._model_units("time")
        if not extent or not time:
            return None
        return self.per(extent, time)
