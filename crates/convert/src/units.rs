//! CellML units as SBML unit definitions.
//!
//! The standard units of CellML are base units of SBML level 3 and are used
//! by name. A custom units becomes a unit definition whose units reference
//! base units only: a reference to other custom units is expanded. A CellML
//! unit is `multiplier * (10^prefix * reference)^exponent` and an SBML unit
//! `(multiplier * 10^scale * kind)^exponent`, so the prefix becomes the
//! scale and the multiplier is taken to the root of the exponent, as in the
//! python converter.

use crate::ids::{sanitize_id, unique_sid};
use cellml::{Model, Units};
use sbml::{Unit, UnitDefinition, UnitKind};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

/// The SBML unit kind CellML has no name for: new base units of this name
/// are the kind itself.
const ITEM: &str = "item";

/// A failure to convert units.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum UnitsError {
    /// A unit references units which the model does not define and which
    /// are no units of CellML.
    #[error("units '{reference}' referenced by '{units}' are not defined")]
    Undefined {
        /// The name of the reference.
        reference: String,
        /// The name of the units which reference it.
        units: String,
    },
    /// A unit has a prefix which is neither a name nor an exponent of ten.
    #[error("unknown unit prefix '{0}'")]
    Prefix(String),
}

/// The power of ten of a prefix: a name of the SI prefixes, an exponent of
/// ten as text, or nothing.
fn prefix_scale(prefix: Option<&str>) -> Result<i32, UnitsError> {
    let Some(prefix) = prefix else {
        return Ok(0);
    };
    let prefix = prefix.trim();
    if prefix.is_empty() {
        return Ok(0);
    }
    const PREFIXES: [(&str, i32); 20] = [
        ("yotta", 24),
        ("zetta", 21),
        ("exa", 18),
        ("peta", 15),
        ("tera", 12),
        ("giga", 9),
        ("mega", 6),
        ("kilo", 3),
        ("hecto", 2),
        ("deca", 1),
        ("deci", -1),
        ("centi", -2),
        ("milli", -3),
        ("micro", -6),
        ("nano", -9),
        ("pico", -12),
        ("femto", -15),
        ("atto", -18),
        ("zepto", -21),
        ("yocto", -24),
    ];
    if let Some((_, scale)) = PREFIXES.iter().find(|(name, _)| *name == prefix) {
        return Ok(*scale);
    }
    prefix
        .parse::<i32>()
        .map_err(|_| UnitsError::Prefix(prefix.to_string()))
}

/// A value with 15 significant digits, so that the noise of a root is
/// gone: `60.00000000000001` is `60`.
fn round(value: f64) -> f64 {
    format!("{value:.14e}").parse().unwrap_or(value)
}

/// Whether custom units are the SBML unit kind `item`, which CellML writes
/// as new base units of that name.
fn is_item(units: &Units) -> bool {
    units.name == ITEM && units.units.is_empty()
}

/// The unit definitions of a model and the id of every units of it.
#[derive(Debug, Clone, Default)]
pub struct UnitIds {
    /// The id of the unit definition of a name of custom units.
    ids: HashMap<String, String>,
}

impl UnitIds {
    /// The SBML id of a name of units: the id of the definition for custom
    /// units, the name itself for the units of CellML, which are the base
    /// units of SBML, and `None` for a name the model does not define,
    /// which SBML has no unit for.
    pub fn resolve(&self, name: &str) -> Option<String> {
        self.ids
            .get(name)
            .cloned()
            .or_else(|| UnitKind::is_kind(name).then(|| name.to_string()))
    }

    /// The id of the unit definition of a name of units, `None` for units
    /// of CellML which are the base units of SBML and need no definition.
    pub fn definition(&self, name: &str) -> Option<&str> {
        self.ids.get(name).map(String::as_str)
    }

    /// The SBML id of a name of units, the name itself for one the model
    /// does not define, for the message of a warning.
    pub fn id(&self, name: &str) -> String {
        self.resolve(name).unwrap_or_else(|| name.to_string())
    }
}

/// Every unit definition of a model, with the custom units of its
/// components (CellML 1.0 and 1.1), their ids and what is left out: SBML
/// has no offset, which CellML 1.0 and 1.1 allow on a unit.
///
/// # Arguments
///
/// * `model` - the model.
///
/// # Errors
///
/// Returns the first [`UnitsError`] of the units of the model.
pub fn unit_definitions(
    model: &Model,
) -> Result<(Vec<UnitDefinition>, UnitIds, Vec<String>), UnitsError> {
    let defined = units_by_name(model);
    let mut ids = UnitIds::default();
    let mut definitions = Vec::new();
    let mut warnings = Vec::new();
    for units in ordered_units(model) {
        for unit in &units.units {
            if unit.offset != 0.0 {
                warnings.push(format!(
                    "units '{}' have the offset {} of the unit '{}', which SBML cannot \
                     express: the offset is left out",
                    units.name, unit.offset, unit.units
                ));
            }
        }
    }
    // the name of a base unit of SBML is no id of a unit definition, so
    // custom units of such a name get a numeric suffix
    let mut used: HashSet<String> = UnitKind::names().map(str::to_string).collect();
    for units in ordered_units(model) {
        if is_item(units) {
            ids.ids.insert(ITEM.to_string(), ITEM.to_string());
            continue;
        }
        if ids.ids.contains_key(&units.name) {
            continue;
        }
        let id = unique_sid(&sanitize_id(&units.name), &mut used);
        let mut expanded = expand(units, &defined)?;
        if expanded.is_empty() {
            expanded.push(Unit {
                kind: UnitKind::Dimensionless,
                exponent: 1.0,
                scale: 0,
                multiplier: 1.0,
            });
        }
        let name = (id != units.name).then(|| units.name.clone());
        ids.ids.insert(units.name.clone(), id.clone());
        definitions.push(UnitDefinition {
            id,
            name,
            units: expanded,
        });
    }
    Ok((definitions, ids, warnings))
}

/// The units of the model and of its components, the model first.
fn ordered_units(model: &Model) -> impl Iterator<Item = &Units> {
    model
        .units
        .iter()
        .chain(
            model
                .components
                .iter()
                .flat_map(|component| &component.units),
        )
        .filter(|units| units.import.is_none())
}

/// The units of a model by name, the model before its components.
fn units_by_name(model: &Model) -> HashMap<&str, &Units> {
    let mut defined = HashMap::new();
    for units in ordered_units(model) {
        defined.entry(units.name.as_str()).or_insert(units);
    }
    defined
}

/// Expand units into the base units of SBML.
fn expand(units: &Units, defined: &HashMap<&str, &Units>) -> Result<Vec<Unit>, UnitsError> {
    let mut result = Vec::new();
    for unit in &units.units {
        let scale = prefix_scale(unit.prefix.as_deref())?;
        let (bases, mut factor) = match defined.get(unit.units.as_str()) {
            Some(child) if is_item(child) => (
                vec![Unit {
                    kind: UnitKind::Item,
                    exponent: 1.0,
                    scale,
                    multiplier: 1.0,
                }],
                unit.multiplier,
            ),
            Some(child) => (
                expand(child, defined)?,
                unit.multiplier * 10f64.powf(f64::from(scale) * unit.exponent),
            ),
            None => {
                let kind =
                    UnitKind::from_name(&unit.units).ok_or_else(|| UnitsError::Undefined {
                        reference: unit.units.clone(),
                        units: units.name.clone(),
                    })?;
                (
                    vec![Unit {
                        kind,
                        exponent: 1.0,
                        scale,
                        multiplier: 1.0,
                    }],
                    unit.multiplier,
                )
            }
        };
        for base in bases {
            let exponent = base.exponent * unit.exponent;
            if exponent == 0.0 {
                continue;
            }
            let mut multiplier = base.multiplier;
            if factor != 1.0 {
                multiplier = round(multiplier * factor.powf(1.0 / exponent));
                factor = 1.0;
            }
            result.push(Unit {
                kind: base.kind,
                exponent,
                scale: base.scale,
                multiplier,
            });
        }
        if factor != 1.0 {
            result.push(Unit {
                kind: UnitKind::Dimensionless,
                exponent: 1.0,
                scale: 0,
                multiplier: round(factor),
            });
        }
    }
    Ok(result)
}
