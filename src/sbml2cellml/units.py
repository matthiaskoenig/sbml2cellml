"""Conversion of CellML units to SBML unit definitions.

The standard units of CellML (`second`, `metre`, `kilogram`, `gram`, `mole`,
`litre`, `dimensionless`, `ampere`, `kelvin`, ...) are all unit kinds of SBML
level 3 and are used by name. A custom `Units` becomes a `UnitDefinition`
whose units reference base kinds only: a reference to another custom `Units`
is expanded recursively.
"""

from dataclasses import dataclass
from typing import Any

import libcellml
import libsbml

from sbml2cellml.variables import sanitize_id, unique_sid

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


def expand_units(units: Any, model: libcellml.Model) -> list[BaseUnit]:
    """Expand CellML units into SBML base units.

    A `unit` referencing a standard unit gives one base unit. A `unit`
    referencing a custom `Units` is expanded recursively, every resulting
    exponent multiplied by the outer exponent and the outer factor
    `multiplier * 10^prefix` folded into the multiplier of the first resulting
    unit (as `factor^(1/e)` with `e` the exponent of that unit before the
    multiplication, so that the product stays the same).

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
        kind = libsbml.UnitKind_forName(reference)
        if kind != libsbml.UNIT_KIND_INVALID:
            result.append(BaseUnit(kind, exponent, prefix_scale(prefix), multiplier))
            continue
        child = model.units(reference)
        if child is None:
            raise UnitsConversionError(
                f"Units '{reference}' referenced by '{units.name()}' are not defined."
            )
        expanded = expand_units(child, model)
        if not expanded:
            result.append(
                BaseUnit(
                    libsbml.UNIT_KIND_DIMENSIONLESS,
                    exponent,
                    prefix_scale(prefix),
                    multiplier,
                )
            )
            continue
        factor = multiplier * 10.0 ** prefix_scale(prefix)
        first_exponent = expanded[0].exponent
        if first_exponent == 0:
            raise UnitsConversionError(
                f"Units '{reference}' start with a unit of exponent 0, "
                f"the factor of '{units.name()}' cannot be folded."
            )
        for index, base in enumerate(expanded):
            base_multiplier = base.multiplier
            if index == 0:
                base_multiplier *= factor ** (1.0 / first_exponent)
            result.append(
                BaseUnit(
                    base.kind, base.exponent * exponent, base.scale, base_multiplier
                )
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
