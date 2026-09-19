"""Conversion of CellML units to SBML unit definitions.

The standard units of CellML (`second`, `metre`, `kilogram`, `gram`, `mole`,
`litre`, `dimensionless`, `ampere`, `kelvin`, ...) are all unit kinds of SBML
level 3 and are used by name. A custom `Units` becomes a `UnitDefinition`
whose units reference base kinds only: a reference to another custom `Units`
is expanded recursively.
"""

import logging
from dataclasses import dataclass
from typing import Any

import libcellml
import libsbml

from sbml2cellml.variables import sanitize_id, unique_sid

logger = logging.getLogger(__name__)

#: SBML unit kind without CellML counterpart: new base units of this name
ITEM = "item"

#: SI prefixes of CellML, by name
PREFIXES: dict[str, int] = {
    "yotta": 24,
    "zetta": 21,
    "exa": 18,
    "peta": 15,
    "tera": 12,
    "giga": 9,
    "mega": 6,
    "kilo": 3,
    "hecto": 2,
    "deca": 1,
    "deci": -1,
    "centi": -2,
    "milli": -3,
    "micro": -6,
    "nano": -9,
    "pico": -12,
    "femto": -15,
    "atto": -18,
    "zepto": -21,
    "yocto": -24,
}


class UnitsConversionError(ValueError):
    """CellML units cannot be converted to SBML."""


@dataclass
class BaseUnit:
    """One unit of an SBML unit definition: `(multiplier * 10^scale * kind)^exponent`."""

    kind: int
    exponent: float
    scale: int
    multiplier: float


def prefix_scale(prefix: str) -> int:
    """Scale of a CellML unit prefix.

    Args:
        prefix: SI prefix name (`milli`), an integer string (`-3`) or empty.

    Returns:
        The power of ten.

    Raises:
        UnitsConversionError: if the prefix is unknown.
    """
    if not prefix:
        return 0
    if prefix in PREFIXES:
        return PREFIXES[prefix]
    try:
        return int(prefix)
    except ValueError as err:
        raise UnitsConversionError(f"Unknown unit prefix '{prefix}'.") from err


def _round(value: float) -> float:
    """A float without the noise of a root, `60.00000000000001` is `60.0`."""
    return float(f"{value:.15g}")


def _is_item(units: Any) -> bool:
    """Whether custom units are the SBML unit kind `item`.

    CellML has no `item`; `sbml2cellml` writes it as new base units of that
    name, i.e., units without unit children.
    """
    return units.name() == ITEM and units.unitCount() == 0


def expand_units(units: Any, model: libcellml.Model) -> list[BaseUnit]:
    """Expand CellML units into SBML base units.

    A CellML `unit` stands for `multiplier * (10^prefix * reference)^exponent`,
    an SBML unit for `(multiplier * 10^scale * kind)^exponent`: the prefix
    becomes the scale and the multiplier its root `multiplier^(1/exponent)`.
    A `unit` referencing custom units is expanded recursively, every
    resulting exponent multiplied by the outer exponent and the outer factor
    `multiplier * 10^(prefix * exponent)` folded into the first resulting
    unit. A factor which is left, e.g. of a unit with the exponent 0, becomes
    a `dimensionless` unit with that multiplier.

    New base units (custom units without any `unit`) have no SBML
    counterpart and are dropped with a warning, except for `item`.

    Args:
        units: libcellml units.
        model: model the units belong to, resolves references to custom units.

    Returns:
        The base units, empty for units without any `unit` (dimensionless).

    Raises:
        UnitsConversionError: for an unknown reference or prefix.
    """
    result: list[BaseUnit] = []
    for k in range(units.unitCount()):
        reference, prefix, exponent, multiplier, _ = units.unitAttributes(k)
        scale = prefix_scale(prefix)
        bases: list[BaseUnit]
        if model.hasUnits(reference):
            child = model.units(reference)
            if _is_item(child):
                bases = [BaseUnit(libsbml.UNIT_KIND_ITEM, 1.0, scale, 1.0)]
                factor = multiplier
            else:
                if child.unitCount() == 0:
                    logger.warning(
                        "Units '%s' are new base units, which SBML does not have: "
                        "dimensionless in '%s'.",
                        reference,
                        units.name(),
                    )
                bases = expand_units(child, model)
                factor = multiplier * 10.0 ** (scale * exponent)
        else:
            kind = libsbml.UnitKind_forName(reference)
            if kind == libsbml.UNIT_KIND_INVALID:
                raise UnitsConversionError(
                    f"Units '{reference}' referenced by '{units.name()}' are not "
                    f"defined."
                )
            bases = [BaseUnit(kind, 1.0, scale, 1.0)]
            factor = multiplier
        for base in bases:
            final = base.exponent * exponent
            if final == 0:
                continue
            base_multiplier = base.multiplier
            if factor != 1.0:
                base_multiplier = _round(base_multiplier * factor ** (1.0 / final))
                factor = 1.0
            result.append(BaseUnit(base.kind, final, base.scale, base_multiplier))
        if factor != 1.0:
            result.append(
                BaseUnit(libsbml.UNIT_KIND_DIMENSIONLESS, 1.0, 0, _round(factor))
            )
    return result


def add_units(
    model_cellml: libcellml.Model, model_sbml: libsbml.Model
) -> dict[str, str]:
    """Add a unit definition for every custom units of a CellML model.

    Args:
        model_cellml: CellML model.
        model_sbml: SBML model the definitions are added to.

    Returns:
        The SBML unit id by CellML units name, for `unit_id`.
    """
    ids: dict[str, str] = {}
    # predefined SBML unit kind names (`second`, `item`, `avogadro`, ...) are
    # rejected as unit definition ids, so a custom units of that name must
    # get a numeric suffix
    used: set[str] = {
        name
        for kind in range(libsbml.UNIT_KIND_INVALID)
        if (name := libsbml.UnitKind_toString(kind))
    }
    for k in range(model_cellml.unitsCount()):
        units = model_cellml.units(k)
        if _is_item(units):
            ids[ITEM] = ITEM
            continue
        uid = unique_sid(sanitize_id(units.name()), used)
        definition = model_sbml.createUnitDefinition()
        definition.setId(uid)
        if uid != units.name():
            definition.setName(units.name())
        expanded = expand_units(units, model_cellml)
        if not expanded:
            expanded = [BaseUnit(libsbml.UNIT_KIND_DIMENSIONLESS, 1.0, 0, 1.0)]
        for base in expanded:
            unit = definition.createUnit()
            unit.setKind(base.kind)
            unit.setExponent(base.exponent)
            unit.setScale(base.scale)
            unit.setMultiplier(base.multiplier)
        ids[units.name()] = uid
    return ids


def unit_id(units_name: str, unit_ids: dict[str, str]) -> str:
    """SBML unit id of a CellML units name.

    Args:
        units_name: name of the units of a variable.
        unit_ids: result of `add_units`.

    Returns:
        The unit definition id for custom units, the name itself for standard units.
    """
    return unit_ids.get(units_name, units_name)
