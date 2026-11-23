//! The elements of an SBML level 3 version 2 model.

use crate::math::Math;

/// An SBML document: the level, the version and the model are fixed, the
/// converter writes level 3 version 2.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Document {
    /// The model of the document.
    pub model: Model,
}

/// An SBML model, with what the conversion of a CellML model needs.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Model {
    /// The id of the model.
    pub id: Option<String>,
    /// The name of the model, the name of the CellML model.
    pub name: Option<String>,
    /// The units of time, the units of the variable of integration.
    pub time_units: Option<String>,
    /// The unit definitions, one per custom units of the CellML model.
    pub unit_definitions: Vec<UnitDefinition>,
    /// The parameters, one per equivalence set of variables.
    pub parameters: Vec<Parameter>,
    /// The initial assignments of the computed constants.
    pub initial_assignments: Vec<InitialAssignment>,
    /// The rules of the equations.
    pub rules: Vec<Rule>,
}

/// A unit definition, the units of the SBML model it references expanded to
/// base units.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct UnitDefinition {
    /// The id.
    pub id: String,
    /// The name of the CellML units, when the id is not that name.
    pub name: Option<String>,
    /// The base units it is the product of, `dimensionless` when empty.
    pub units: Vec<Unit>,
}

/// One unit of a unit definition, `(multiplier * 10^scale * kind)^exponent`.
#[derive(Debug, Clone, PartialEq)]
pub struct Unit {
    /// The base unit.
    pub kind: UnitKind,
    /// The exponent.
    pub exponent: f64,
    /// The power of ten.
    pub scale: i32,
    /// The factor.
    pub multiplier: f64,
}

/// A parameter of the model, one per equivalence set of CellML variables.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Parameter {
    /// The id.
    pub id: String,
    /// The name of the CellML variable, when the id is not that name.
    pub name: Option<String>,
    /// The value, absent when an initial assignment or a rule gives it.
    pub value: Option<f64>,
    /// The id of its units.
    pub units: Option<String>,
    /// Whether the value never changes.
    pub constant: bool,
}

/// An initial assignment, the value of a parameter at the start.
#[derive(Debug, Clone, PartialEq)]
pub struct InitialAssignment {
    /// The id of the parameter it gives the value.
    pub symbol: String,
    /// The expression of the value.
    pub math: Math,
}

/// A rule of the model, one per equation of the CellML model.
#[derive(Debug, Clone, PartialEq)]
pub enum Rule {
    /// `variable = math` at every point in time.
    Assignment {
        /// The id of the parameter the rule determines.
        variable: String,
        /// The right hand side.
        math: Math,
    },
    /// `d variable / d time = math`.
    Rate {
        /// The id of the parameter the rule integrates.
        variable: String,
        /// The right hand side.
        math: Math,
    },
    /// `0 = math`, an equation which determines no single variable.
    Algebraic {
        /// The residual.
        math: Math,
    },
}

/// A base unit of SBML level 3, the `kind` of a unit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[expect(missing_docs, reason = "the name of every unit is its documentation")]
pub enum UnitKind {
    Ampere,
    Avogadro,
    Becquerel,
    Candela,
    Coulomb,
    Dimensionless,
    Farad,
    Gram,
    Gray,
    Henry,
    Hertz,
    Item,
    Joule,
    Katal,
    Kelvin,
    Kilogram,
    Litre,
    Lumen,
    Lux,
    Metre,
    Mole,
    Newton,
    Ohm,
    Pascal,
    Radian,
    Second,
    Siemens,
    Sievert,
    Steradian,
    Tesla,
    Volt,
    Watt,
    Weber,
}

/// Every base unit of SBML level 3, by its name.
const KINDS: [(&str, UnitKind); 33] = [
    ("ampere", UnitKind::Ampere),
    ("avogadro", UnitKind::Avogadro),
    ("becquerel", UnitKind::Becquerel),
    ("candela", UnitKind::Candela),
    ("coulomb", UnitKind::Coulomb),
    ("dimensionless", UnitKind::Dimensionless),
    ("farad", UnitKind::Farad),
    ("gram", UnitKind::Gram),
    ("gray", UnitKind::Gray),
    ("henry", UnitKind::Henry),
    ("hertz", UnitKind::Hertz),
    ("item", UnitKind::Item),
    ("joule", UnitKind::Joule),
    ("katal", UnitKind::Katal),
    ("kelvin", UnitKind::Kelvin),
    ("kilogram", UnitKind::Kilogram),
    ("litre", UnitKind::Litre),
    ("lumen", UnitKind::Lumen),
    ("lux", UnitKind::Lux),
    ("metre", UnitKind::Metre),
    ("mole", UnitKind::Mole),
    ("newton", UnitKind::Newton),
    ("ohm", UnitKind::Ohm),
    ("pascal", UnitKind::Pascal),
    ("radian", UnitKind::Radian),
    ("second", UnitKind::Second),
    ("siemens", UnitKind::Siemens),
    ("sievert", UnitKind::Sievert),
    ("steradian", UnitKind::Steradian),
    ("tesla", UnitKind::Tesla),
    ("volt", UnitKind::Volt),
    ("watt", UnitKind::Watt),
    ("weber", UnitKind::Weber),
];

impl UnitKind {
    /// The base unit of a name, `None` for a name which is none of them.
    pub fn from_name(name: &str) -> Option<Self> {
        KINDS
            .iter()
            .find(|(candidate, _)| *candidate == name)
            .map(|(_, kind)| *kind)
    }

    /// The name of the base unit.
    pub fn name(self) -> &'static str {
        KINDS
            .iter()
            .find(|(_, kind)| *kind == self)
            .map(|(name, _)| *name)
            .unwrap_or("dimensionless")
    }

    /// Whether a name is a base unit of SBML level 3.
    pub fn is_kind(name: &str) -> bool {
        Self::from_name(name).is_some()
    }

    /// The name of every base unit of SBML level 3, which is no id of a
    /// unit definition.
    pub fn names() -> impl Iterator<Item = &'static str> {
        KINDS.iter().map(|(name, _)| *name)
    }
}
