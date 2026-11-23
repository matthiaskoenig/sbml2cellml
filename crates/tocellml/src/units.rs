//! The CellML units of an SBML model, the port of `cellmlunits.py`.
//!
//! Every unit definition of the model becomes CellML units of the same name.
//! An SBML unit stands for `(multiplier * 10^scale * kind)^exponent` and a
//! CellML unit for `multiplier * (10^prefix * reference)^exponent`: the scale
//! becomes the prefix, together with a multiplier which is a power of ten, and
//! any other multiplier becomes its power `multiplier^exponent`. The unit
//! kinds of SBML are the standard units of CellML, except for `item`, which
//! becomes new base units, and `avogadro`, which becomes the dimensionless
//! units of that number.
//!
//! [`Units`] also gives the units of the elements which become variables: a
//! compartment, a parameter and a species with only substance units reference
//! their units, a species in concentration has the units of its substance per
//! the units of its compartment, and the rate of a reaction the units of the
//! extent per the units of time. For such a quotient the unit definition of
//! the model which is identical to it is taken, else units
//! `numerator_per_denominator` are added.

use crate::ids::unique_name;
use cellml::{Unit as CellMLUnit, Units as CellMLUnits};
use sbml::{Compartment, Model, Species, Unit, UnitDefinition};
use std::collections::{HashMap, HashSet};

/// The units of a quantity without units.
pub const DIMENSIONLESS: &str = "dimensionless";

/// The unit kind which becomes new base units, CellML has no name for it.
const ITEM: &str = "item";

/// The unit kind which becomes the dimensionless units of its value.
const AVOGADRO: &str = "avogadro";

/// The value of the avogadro constant, the one SBML defines for its symbol,
/// which is not the value of the SI of 2019 (`6.02214076e23`).
pub const AVOGADRO_VALUE: f64 = 6.022_141_79e23;

/// The units CellML has built in, every one of them a unit kind of SBML.
const STANDARD_UNITS: [&str; 31] = [
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
];

/// The SI prefixes of CellML by their power of ten.
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

/// The units which SBML level 1 and 2 have built in, as the kind and the
/// exponent they stand for.
const BUILTIN_UNITS: [(&str, &str, f64); 5] = [
    ("substance", "mole", 1.0),
    ("time", "second", 1.0),
    ("volume", "litre", 1.0),
    ("area", "metre", 2.0),
    ("length", "metre", 1.0),
];

/// The spellings of the unit kinds which only SBML level 1 and 2 have.
const KIND_SPELLINGS: [(&str, &str); 2] = [("liter", "litre"), ("meter", "metre")];

/// The units of the model the size of a compartment of that many dimensions
/// is in.
const SIZE_UNITS: [(f64, &str); 3] = [(3.0, "volume"), (2.0, "area"), (1.0, "length")];

/// A value with 15 significant digits, so the noise of a power is gone:
/// `0.010000000000000002` is `0.01`.
fn round(value: f64) -> f64 {
    format!("{value:.14e}").parse().unwrap_or(value)
}

/// Move a multiplier which is a power of ten into the scale.
///
/// `1000 gram` is `kilo gram`: a prefix reads better than a multiplier and,
/// unlike the multiplier, is inside the exponent in CellML as well.
fn power_of_ten(scale: i32, multiplier: f64) -> (i32, f64) {
    if multiplier > 0.0 {
        let power = multiplier.log10().round();
        if (multiplier - 10f64.powf(power)).abs() <= 1e-12 * multiplier.abs() {
            #[expect(
                clippy::cast_possible_truncation,
                reason = "the power of a multiplier of a unit is small"
            )]
            return (scale + power as i32, 1.0);
        }
    }
    (scale, multiplier)
}

/// The name of the prefix of a power of ten, the power itself as text when no
/// prefix stands for it.
fn prefix(scale: i32) -> Option<String> {
    if scale == 0 {
        return None;
    }
    PREFIXES
        .iter()
        .find(|(_, power)| *power == scale)
        .map(|(name, _)| (*name).to_string())
        .or_else(|| Some(scale.to_string()))
}

/// What is said about a unit of a definition which is not converted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Warning(pub String);

/// The CellML units of an SBML model.
#[derive(Debug, Clone, Default)]
pub struct Units {
    /// The unit definitions of the CellML model, in the order they are added.
    definitions: Vec<CellMLUnits>,
    /// The name of the CellML units of an SBML unit reference.
    names: HashMap<String, String>,
    /// The names which are taken.
    used: HashSet<String>,
    /// The level of the document, which decides whether the model has the
    /// units built in.
    level: u32,
    /// What was not converted.
    warnings: Vec<String>,
}

impl Units {
    /// Convert the unit definitions of an SBML model.
    #[must_use]
    pub fn new(model: &Model, level: u32) -> Self {
        let mut units = Self {
            level,
            used: STANDARD_UNITS.iter().map(|n| (*n).to_string()).collect(),
            ..Self::default()
        };
        for definition in &model.unit_definitions {
            // the reader defines the units every level before 3 has built in
            // for every such model; they are the references `substance`,
            // `volume`, `area`, `length` and `time`, which `name` resolves to
            // the kind itself, so the CellML model needs no definition of
            // them, where a model which states them itself gets its own
            if definition.built_in {
                continue;
            }
            units.add_definition(definition);
        }
        units
    }

    /// The unit definitions of the CellML model.
    #[must_use]
    pub fn definitions(&self) -> &[CellMLUnits] {
        &self.definitions
    }

    /// What was not converted, one line each.
    #[must_use]
    pub fn warnings(&self) -> &[String] {
        &self.warnings
    }

    /// A CellML identifier which no other units have.
    fn unique(&mut self, name: &str) -> String {
        // an id of SBML may start with an underscore, a name of CellML may not
        let name = if name.starts_with(|c: char| c.is_alphabetic()) {
            name.to_string()
        } else {
            format!("u{name}")
        };
        unique_name(&name, &mut self.used)
    }

    /// Add new units to the model under a name which is free.
    fn add(&mut self, name: &str, units: Vec<CellMLUnit>) -> String {
        let name = self.unique(name);
        self.definitions.push(CellMLUnits {
            name: name.clone(),
            base_units: false,
            units,
            import: None,
        });
        name
    }

    /// The CellML units of a unit definition of the model.
    fn add_definition(&mut self, definition: &UnitDefinition) {
        let mut units = Vec::new();
        for unit in &definition.units {
            let Some(reference) = self.kind(&unit.kind) else {
                self.warnings.push(format!(
                    "unit of kind '{}' in unit definition '{}' not converted, CellML does not have it",
                    unit.kind, definition.id
                ));
                continue;
            };
            let (scale, multiplier) = power_of_ten(unit.scale, unit.multiplier);
            units.push(CellMLUnit {
                units: reference,
                prefix: prefix(scale),
                exponent: unit.exponent,
                multiplier: round(multiplier.powf(unit.exponent)),
                offset: 0.0,
            });
        }
        let name = self.add(&definition.id, units);
        self.names.insert(definition.id.clone(), name);
    }

    /// The CellML units of an SBML unit kind, added to the model when CellML
    /// does not have them; `None` for a kind CellML has no units for, such as
    /// the `celsius` of SBML level 2 version 1.
    fn kind(&mut self, kind: &str) -> Option<String> {
        let name = KIND_SPELLINGS
            .iter()
            .find(|(spelling, _)| *spelling == kind)
            .map_or(kind, |(_, name)| *name);
        if name == ITEM || name == AVOGADRO {
            if let Some(known) = self.names.get(name) {
                return Some(known.clone());
            }
            // `item` is new base units, `avogadro` the dimensionless units of
            // the number the symbol of SBML stands for
            let units = if name == AVOGADRO {
                vec![CellMLUnit {
                    units: DIMENSIONLESS.to_string(),
                    prefix: None,
                    exponent: 1.0,
                    multiplier: AVOGADRO_VALUE,
                    offset: 0.0,
                }]
            } else {
                Vec::new()
            };
            let added = self.add(name, units);
            self.names.insert(name.to_string(), added.clone());
            return Some(added);
        }
        STANDARD_UNITS.contains(&name).then(|| name.to_string())
    }

    /// The CellML units of an SBML unit reference: the id of a unit
    /// definition, the name of a unit kind or units which the level has built
    /// in (`substance`); `None` for a reference the model does not define.
    pub fn name(&mut self, reference: &str) -> Option<String> {
        if reference.is_empty() {
            return None;
        }
        if let Some(name) = self.names.get(reference) {
            return Some(name.clone());
        }
        if let Some(name) = self.kind(reference) {
            return Some(name);
        }
        if self.level >= 3 {
            return None;
        }
        // the units of level 1 and 2 which the model does not redefine
        let (_, kind, exponent) = *BUILTIN_UNITS
            .iter()
            .find(|(name, _, _)| *name == reference)?;
        if exponent == 1.0 {
            return self.kind(kind);
        }
        let reference_units = vec![CellMLUnit {
            units: self.kind(kind)?,
            prefix: None,
            exponent,
            multiplier: 1.0,
            offset: 0.0,
        }];
        let name = self.add(reference, reference_units);
        self.names.insert(reference.to_string(), name.clone());
        Some(name)
    }

    /// The CellML units of the `sbml:units` of a number in a formula: the
    /// reference itself when the model does not define it, which the
    /// validation of the CellML model reports.
    pub fn number_units(&mut self, reference: &str) -> String {
        self.name(reference)
            .unwrap_or_else(|| reference.to_string())
    }
}

/// Every unit kind of SBML, the spellings of level 1 and 2 included.
const KINDS: [&str; 36] = [
    "ampere",
    "avogadro",
    "becquerel",
    "candela",
    "celsius",
    "coulomb",
    "dimensionless",
    "farad",
    "gram",
    "gray",
    "henry",
    "hertz",
    "item",
    "joule",
    "katal",
    "kelvin",
    "kilogram",
    "liter",
    "litre",
    "lumen",
    "lux",
    "meter",
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
];

impl Units {
    /// The units of the model of a quantity, which SBML level 1 and 2 have
    /// built in and level 3 states; `None` for a level 3 model which does not.
    fn model_units(model: &Model, quantity: &str) -> Option<String> {
        match quantity {
            "substance" => model.substance_units.clone(),
            "time" => model.time_units.clone(),
            "volume" => model.volume_units.clone(),
            "area" => model.area_units.clone(),
            "length" => model.length_units.clone(),
            "extent" => model.extent_units.clone(),
            _ => None,
        }
    }

    /// The unit reference of the size of a compartment.
    fn compartment_reference(&self, model: &Model, compartment: &Compartment) -> Option<String> {
        if let Some(units) = &compartment.units {
            return Some(units.clone());
        }
        // the dimensions of a compartment of level 1 and 2 are 3 by default,
        // a compartment of level 3 which does not state them has no size units
        let dimensions = compartment
            .spatial_dimensions
            .or_else(|| (self.level < 3).then_some(3.0))?;
        if dimensions == 0.0 {
            return Some(DIMENSIONLESS.to_string());
        }
        let (_, quantity) = *SIZE_UNITS.iter().find(|(size, _)| *size == dimensions)?;
        Self::model_units(model, quantity)
    }

    /// The unit reference of the substance of a species.
    fn substance_reference(&self, model: &Model, species: &Species) -> Option<String> {
        species
            .substance_units
            .clone()
            .or_else(|| Self::model_units(model, "substance"))
    }

    /// The units of a unit reference as the units of SBML, so that two
    /// references can be compared: the units of a definition of the model, a
    /// unit kind as itself, or the units which the level has built in.
    fn expand(&self, model: &Model, reference: &str) -> Option<Vec<Unit>> {
        if let Some(definition) = model
            .unit_definitions
            .iter()
            .find(|definition| definition.id == reference)
        {
            return Some(definition.units.clone());
        }
        let unit = |kind: &str, exponent: f64| {
            vec![Unit {
                kind: kind.to_string(),
                exponent,
                scale: 0,
                multiplier: 1.0,
            }]
        };
        if KINDS.contains(&reference) {
            return Some(unit(reference, 1.0));
        }
        if self.level >= 3 {
            return None;
        }
        let (_, kind, exponent) = *BUILTIN_UNITS
            .iter()
            .find(|(name, _, _)| *name == reference)?;
        Some(unit(kind, exponent))
    }

    /// The CellML units of the quotient of two unit references, e.g. the
    /// substance of a species per the size of its compartment.
    ///
    /// The unit definition of the model which is identical to the quotient is
    /// taken, else units `numerator_per_denominator` are added to the model.
    /// `None` when the model defines one of the two references nowhere.
    pub fn per(&mut self, model: &Model, numerator: &str, denominator: &str) -> Option<String> {
        let key = format!("{numerator}/{denominator}");
        if let Some(name) = self.names.get(&key) {
            return Some(name.clone());
        }
        let (top, bottom) = (self.name(numerator)?, self.name(denominator)?);
        let quotient: Vec<Unit> = self
            .expand(model, numerator)?
            .into_iter()
            .chain(
                self.expand(model, denominator)?
                    .into_iter()
                    .map(|unit| Unit {
                        exponent: -unit.exponent,
                        ..unit
                    }),
            )
            .collect();
        for definition in &model.unit_definitions {
            if identical(&quotient, &definition.units) {
                let name = self.names.get(&definition.id)?.clone();
                self.names.insert(key, name.clone());
                return Some(name);
            }
        }
        let units = vec![
            CellMLUnit {
                units: top.clone(),
                prefix: None,
                exponent: 1.0,
                multiplier: 1.0,
                offset: 0.0,
            },
            CellMLUnit {
                units: bottom.clone(),
                prefix: None,
                exponent: -1.0,
                multiplier: 1.0,
                offset: 0.0,
            },
        ];
        let name = self.add(&format!("{top}_per_{bottom}"), units);
        self.names.insert(key, name.clone());
        Some(name)
    }

    /// The CellML units of time, `None` when the model does not state them.
    pub fn time(&mut self, model: &Model) -> Option<String> {
        let reference = Self::model_units(model, "time")?;
        self.name(&reference)
    }

    /// The CellML units of the size of a compartment, `None` when unknown.
    pub fn of_compartment(&mut self, model: &Model, compartment: &Compartment) -> Option<String> {
        let reference = self.compartment_reference(model, compartment)?;
        self.name(&reference)
    }

    /// The CellML units of a parameter, `None` when it has none.
    pub fn of_parameter(&mut self, units: Option<&str>) -> Option<String> {
        self.name(units?)
    }

    /// The CellML units of the amount of a species, `None` when unknown.
    pub fn of_amount(&mut self, model: &Model, species: &Species) -> Option<String> {
        let reference = self.substance_reference(model, species)?;
        self.name(&reference)
    }

    /// The CellML units of a species: its substance when it has only
    /// substance units or its compartment no dimensions, else the
    /// concentration, the substance per the size of the compartment.
    pub fn of_species(&mut self, model: &Model, species: &Species) -> Option<String> {
        let substance = self.substance_reference(model, species)?;
        if species.has_only_substance_units {
            return self.name(&substance);
        }
        let compartment = model
            .compartments
            .iter()
            .find(|compartment| compartment.id == species.compartment)?;
        let size = self.compartment_reference(model, compartment)?;
        if size == DIMENSIONLESS {
            return self.name(&substance);
        }
        self.per(model, &substance, &size)
    }

    /// The CellML units of the rate of a reaction, the extent per time.
    pub fn of_reaction(&mut self, model: &Model) -> Option<String> {
        let extent = Self::model_units(model, "extent")?;
        let time = Self::model_units(model, "time")?;
        self.per(model, &extent, &time)
    }
}

/// Whether two lists of SBML units mean the same units: the same exponent
/// per unit kind and the same factor.
///
/// The python converter asks libsbml (`UnitDefinition::areIdentical`),
/// which compares the scale and the multiplier of every unit as the
/// document states them, so it does not take a definition which means the
/// same units and writes them differently (a scale of `-3` against a
/// multiplier of `0.001`); this comparison does, and the two converters
/// name such units differently. The units are the same either way, which
/// `scripts/sbml2cellml_parity.py` compares.
fn identical(one: &[Unit], other: &[Unit]) -> bool {
    let normalize = |units: &[Unit]| {
        let mut exponents: HashMap<String, f64> = HashMap::new();
        let mut factor = 1.0;
        for unit in units {
            *exponents.entry(unit.kind.clone()).or_default() += unit.exponent;
            factor *= (unit.multiplier * 10f64.powi(unit.scale)).powf(unit.exponent);
        }
        exponents.retain(|_, exponent| *exponent != 0.0);
        (exponents, factor)
    };
    let (ours, our_factor) = normalize(one);
    let (theirs, their_factor) = normalize(other);
    ours == theirs && (our_factor - their_factor).abs() <= 1e-12 * our_factor.abs().max(1.0)
}

/// Whether the SBML model says anything about units at all.
///
/// The units which level 1 and 2 have built in do not count, since the reader
/// defines them for every such model: a model without any unit of its own is
/// not an incomplete annotation but no annotation.
#[must_use]
pub fn is_annotated(model: &Model, level: u32) -> bool {
    let model_units = level >= 3
        && [
            &model.substance_units,
            &model.time_units,
            &model.volume_units,
            &model.area_units,
            &model.length_units,
            &model.extent_units,
        ]
        .iter()
        .any(|units| units.is_some());
    model
        .unit_definitions
        .iter()
        .any(|definition| !definition.built_in)
        || model_units
        || model.compartments.iter().any(|c| c.units.is_some())
        || model.parameters.iter().any(|p| p.units.is_some())
        || model.species.iter().any(|s| s.substance_units.is_some())
}
