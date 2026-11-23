//! The evaluation of the formulas of an SBML model at the start.
//!
//! CellML has no initial assignment: a variable carries a number, so the
//! conversion evaluates what the SBML model computes at the start, as the
//! python converter has libsbml evaluate it. [`Start`] is the values of the
//! quantities of the model: a quantity which an initial assignment or an
//! assignment rule computes has the value of that formula, every other one
//! the value the model states, and the evaluation of a formula reads them.
//!
//! The value of a species is the quantity a formula of SBML means: the
//! amount of a species with `hasOnlySubstanceUnits` and the concentration
//! of every other one, converted with the size of its compartment when the
//! model states the other quantity.
//!
//! The evaluation is the one of the simulator of SBML (`sbmlsim-ir`): a
//! value which is no boolean is true when it is not zero, `plus()` is 0 and
//! `times()` is 1, a relation of more than two arguments holds when it
//! holds for every pair, and `quotient` and `rem` are the integer division
//! of the OpenMath dictionary which the MathML of SBML follows, which
//! truncates towards zero.

use std::collections::HashMap;

use sbml::Model;
use sbml::math::{Node as Sbml, Op};
use thiserror::Error;

/// What the evaluation of a formula at the start does not give a value.
#[derive(Debug, Error, PartialEq)]
pub enum EvalError {
    /// A symbol which is no quantity of the model.
    #[error("'{0}' has no value at the start")]
    Unknown(String),
    /// A quantity whose value needs itself.
    #[error("the value of '{0}' needs itself")]
    Cycle(String),
    /// An operator which has no value at the start: a delay, and a `rateOf`
    /// or a call of a function definition which the conversion did not
    /// expand.
    #[error("'{0}' has no value at the start")]
    Operator(String),
    /// A formula without mathematics.
    #[error("the formula is empty")]
    Empty,
}

/// The values of the quantities of an SBML model at the start.
pub struct Start<'a> {
    model: &'a Model,
    assignments: HashMap<&'a str, &'a Sbml>,
    rules: HashMap<&'a str, &'a Sbml>,
    rates: HashMap<&'a str, &'a Sbml>,
    locals: HashMap<String, f64>,
    overrides: HashMap<String, f64>,
    values: HashMap<String, f64>,
    pending: Vec<String>,
}

impl<'a> Start<'a> {
    /// The values of a model, with the formulas the conversion expanded.
    ///
    /// Args:
    ///     model: the SBML model.
    ///     assignments: the formula of every initial assignment, by symbol.
    ///     rules: the formula of every assignment rule, by variable.
    ///     rates: the kinetic law of every reaction, by reaction; the value
    ///         of a reaction is its rate, which a formula may read.
    ///     locals: the value of the variable of every local parameter of a
    ///         kinetic law, which the formula of a rate reads.
    #[must_use]
    pub fn new(
        model: &'a Model,
        assignments: &'a [(String, Sbml)],
        rules: &'a [(String, Sbml)],
        rates: &'a [(String, Sbml)],
        locals: HashMap<String, f64>,
    ) -> Self {
        let by_id = |pairs: &'a [(String, Sbml)]| {
            pairs
                .iter()
                .map(|(id, formula)| (id.as_str(), formula))
                .collect()
        };
        Self {
            model,
            assignments: by_id(assignments),
            rules: by_id(rules),
            rates: by_id(rates),
            locals,
            overrides: HashMap::new(),
            values: HashMap::new(),
            pending: Vec::new(),
        }
    }

    /// Gives a quantity a value, whatever the model states: the value of
    /// the variable of an algebraic rule while it is solved.
    ///
    /// Every value which was evaluated before is evaluated again, since it
    /// may read the quantity.
    pub fn override_value(&mut self, id: &str, value: f64) {
        self.overrides.insert(id.to_string(), value);
        self.values.clear();
    }

    /// Whether an initial assignment gives the quantity its value.
    #[must_use]
    pub fn is_assigned(&self, id: &str) -> bool {
        self.assignments.contains_key(id)
    }

    /// The value of a quantity of the model at the start.
    ///
    /// An initial assignment of the quantity gives it its value, else an
    /// assignment rule of it, else the value the model states, which is the
    /// value a simulator takes when the model states none (0 for the amount
    /// of a species and 1 for a compartment, a parameter and a
    /// stoichiometry).
    ///
    /// Errors:
    ///     `EvalError` when the value cannot be evaluated.
    pub fn value(&mut self, id: &str) -> Result<f64, EvalError> {
        if let Some(value) = self.values.get(id) {
            return Ok(*value);
        }
        if self.pending.iter().any(|pending| pending == id) {
            return Err(EvalError::Cycle(id.to_string()));
        }
        self.pending.push(id.to_string());
        let value = self.computed(id);
        self.pending.pop();
        let value = value?;
        self.values.insert(id.to_string(), value);
        Ok(value)
    }

    /// The value of a quantity, without the cache and the cycle check.
    fn computed(&mut self, id: &str) -> Result<f64, EvalError> {
        if let Some(value) = self.overrides.get(id) {
            return Ok(*value);
        }
        if let Some(formula) = self.assignments.get(id).copied() {
            return self.eval(formula);
        }
        if let Some(formula) = self.rules.get(id).copied() {
            return self.eval(formula);
        }
        // the value of a reaction is its rate, which the conversion writes
        // as the variable of the reaction
        if let Some(formula) = self.rates.get(id).copied() {
            return self.eval(formula);
        }
        if let Some(value) = self.locals.get(id) {
            return Ok(*value);
        }
        if let Some(compartment) = self.model.compartments.iter().find(|c| c.id == id) {
            return Ok(compartment.size.unwrap_or(1.0));
        }
        if let Some(species) = self.model.species.iter().find(|s| s.id == id) {
            return self.of_species(&species.id);
        }
        if let Some(parameter) = self.model.parameters.iter().find(|p| p.id == id) {
            return Ok(parameter.value.unwrap_or(1.0));
        }
        if let Some(reference) = self
            .model
            .reactions
            .iter()
            .flat_map(|reaction| reaction.reactants.iter().chain(reaction.products.iter()))
            .find(|reference| reference.id.as_deref() == Some(id))
        {
            return Ok(reference.stoichiometry.unwrap_or(1.0));
        }
        Err(EvalError::Unknown(id.to_string()))
    }

    /// The value of a species, the quantity a formula of SBML means.
    fn of_species(&mut self, id: &str) -> Result<f64, EvalError> {
        let species = self
            .model
            .species
            .iter()
            .find(|species| species.id == id)
            .ok_or_else(|| EvalError::Unknown(id.to_string()))?;
        let (amount, concentration, compartment, as_amount) = (
            species.initial_amount,
            species.initial_concentration,
            species.compartment.clone(),
            species.has_only_substance_units,
        );
        match (as_amount, amount, concentration) {
            (true, Some(amount), _) => Ok(amount),
            (true, None, Some(concentration)) => Ok(concentration * self.value(&compartment)?),
            (false, _, Some(concentration)) => Ok(concentration),
            (false, Some(amount), None) => Ok(amount / self.value(&compartment)?),
            // the amount a simulator takes when the model states no value
            (true, None, None) => Ok(0.0),
            (false, None, None) => Ok(0.0 / self.value(&compartment)?),
        }
    }

    /// The value of a formula at the start.
    ///
    /// Errors:
    ///     `EvalError` when a part of the formula has no value.
    pub fn eval(&mut self, node: &Sbml) -> Result<f64, EvalError> {
        match node {
            Sbml::Number { value, .. } => Ok(*value),
            Sbml::Symbol(name) => self.value(name),
            Sbml::True => Ok(1.0),
            Sbml::False => Ok(0.0),
            Sbml::Pi => Ok(std::f64::consts::PI),
            Sbml::ExponentialE => Ok(std::f64::consts::E),
            Sbml::Infinity => Ok(f64::INFINITY),
            Sbml::NotANumber => Ok(f64::NAN),
            Sbml::CsymbolAvogadro => Ok(crate::units::AVOGADRO_VALUE),
            // time is zero at the start
            Sbml::CsymbolTime => Ok(0.0),
            Sbml::Apply { op, args } => self.apply(op, args),
            Sbml::Piecewise { pieces, otherwise } => {
                for (value, condition) in pieces {
                    if self.boolean(condition)? {
                        return self.eval(value);
                    }
                }
                match otherwise {
                    Some(value) => self.eval(value),
                    None => Ok(f64::NAN),
                }
            }
            Sbml::CsymbolDelay => Err(EvalError::Operator("delay".to_string())),
            Sbml::CsymbolRateOf => Err(EvalError::Operator("rateOf".to_string())),
            Sbml::Lambda { .. } => Err(EvalError::Operator("lambda".to_string())),
            Sbml::Empty => Err(EvalError::Empty),
        }
    }

    /// The value of a formula as a boolean: a value which is no boolean is
    /// true when it is not zero.
    fn boolean(&mut self, node: &Sbml) -> Result<bool, EvalError> {
        Ok(self.eval(node)?.abs() > 0.0)
    }

    /// The value of an operator applied to its arguments.
    fn apply(&mut self, op: &Op, args: &[Sbml]) -> Result<f64, EvalError> {
        if let Some(value) = self.logical(op, args)? {
            return Ok(value);
        }
        let mut values = Vec::with_capacity(args.len());
        for argument in args {
            values.push(self.eval(argument)?);
        }
        let x = |index: usize| values.get(index).copied().unwrap_or(f64::NAN);
        let value = match op {
            Op::Plus => values.iter().sum(),
            Op::Times => values.iter().product(),
            Op::Minus if values.len() == 1 => -x(0),
            Op::Minus => x(0) - x(1),
            Op::Divide => x(0) / x(1),
            Op::Power => x(0).powf(x(1)),
            Op::Root if values.len() == 1 => x(0).sqrt(),
            Op::Root => x(1).powf(1.0 / x(0)),
            Op::Abs => x(0).abs(),
            Op::Exp => x(0).exp(),
            Op::Ln => x(0).ln(),
            Op::Log if values.len() == 1 => x(0).log10(),
            Op::Log => x(1).log(x(0)),
            Op::Floor => x(0).floor(),
            Op::Ceiling => x(0).ceil(),
            Op::Factorial => factorial(x(0)),
            Op::Sin => x(0).sin(),
            Op::Cos => x(0).cos(),
            Op::Tan => x(0).tan(),
            Op::Sec => 1.0 / x(0).cos(),
            Op::Csc => 1.0 / x(0).sin(),
            Op::Cot => 1.0 / x(0).tan(),
            Op::Sinh => x(0).sinh(),
            Op::Cosh => x(0).cosh(),
            Op::Tanh => x(0).tanh(),
            Op::Sech => 1.0 / x(0).cosh(),
            Op::Csch => 1.0 / x(0).sinh(),
            Op::Coth => 1.0 / x(0).tanh(),
            Op::Arcsin => x(0).asin(),
            Op::Arccos => x(0).acos(),
            Op::Arctan => x(0).atan(),
            Op::Arcsec => (1.0 / x(0)).acos(),
            Op::Arccsc => (1.0 / x(0)).asin(),
            Op::Arccot => (1.0 / x(0)).atan(),
            Op::Arcsinh => x(0).asinh(),
            Op::Arccosh => x(0).acosh(),
            Op::Arctanh => x(0).atanh(),
            Op::Arcsech => (1.0 / x(0)).acosh(),
            Op::Arccsch => (1.0 / x(0)).asinh(),
            Op::Arccoth => (1.0 / x(0)).atanh(),
            Op::Max => values.iter().copied().fold(f64::NEG_INFINITY, f64::max),
            Op::Min => values.iter().copied().fold(f64::INFINITY, f64::min),
            Op::Rem => x(0) % x(1),
            Op::Quotient => (x(0) / x(1)).trunc(),
            Op::Delay => return Err(EvalError::Operator("delay".to_string())),
            Op::RateOf => return Err(EvalError::Operator("rateOf".to_string())),
            Op::Function(name) => return Err(EvalError::Operator(name.clone())),
            Op::Eq | Op::Neq | Op::Gt | Op::Lt | Op::Geq | Op::Leq => f64::NAN,
            Op::And | Op::Or | Op::Xor | Op::Not | Op::Implies => f64::NAN,
        };
        Ok(value)
    }

    /// The value of a relation or of a logical operator, `None` for every
    /// other operator.
    fn logical(&mut self, op: &Op, args: &[Sbml]) -> Result<Option<f64>, EvalError> {
        let truth = match op {
            Op::And => {
                let mut value = true;
                for argument in args {
                    value &= self.boolean(argument)?;
                }
                value
            }
            Op::Or => {
                let mut value = false;
                for argument in args {
                    value |= self.boolean(argument)?;
                }
                value
            }
            Op::Xor => {
                let mut value = false;
                for argument in args {
                    value ^= self.boolean(argument)?;
                }
                value
            }
            Op::Not => !self.boolean(args.first().ok_or(EvalError::Empty)?)?,
            Op::Implies => {
                let (left, right) = (args.first(), args.get(1));
                !self.boolean(left.ok_or(EvalError::Empty)?)?
                    | self.boolean(right.ok_or(EvalError::Empty)?)?
            }
            Op::Eq | Op::Neq | Op::Gt | Op::Lt | Op::Geq | Op::Leq => {
                let mut values = Vec::with_capacity(args.len());
                for argument in args {
                    values.push(self.eval(argument)?);
                }
                values.windows(2).all(|pair| relation(op, pair[0], pair[1]))
            }
            _ => return Ok(None),
        };
        Ok(Some(f64::from(u8::from(truth))))
    }
}

/// Whether a relation holds for two values.
fn relation(op: &Op, left: f64, right: f64) -> bool {
    match op {
        Op::Eq => left == right,
        Op::Neq => left != right,
        Op::Gt => left > right,
        Op::Lt => left < right,
        Op::Geq => left >= right,
        Op::Leq => left <= right,
        _ => false,
    }
}

/// The factorial of a value, NaN for a value which is no whole number or
/// which is negative.
fn factorial(value: f64) -> f64 {
    if value < 0.0 || value.fract() != 0.0 {
        return f64::NAN;
    }
    let mut product = 1.0;
    let mut factor = 2.0;
    while factor <= value {
        product *= factor;
        factor += 1.0;
    }
    product
}
