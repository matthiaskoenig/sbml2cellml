//! The structure of an SBML model as a CellML model.
//!
//! The CellML model is one component, `sbml`, with one variable per
//! compartment, parameter and species plus the variable of integration, as
//! the python converter writes it:
//!
//! - an assignment rule becomes an equation and its target has no initial
//!   value, a rate rule and the reactions of a species a differential
//!   equation
//! - every reaction with a kinetic law is a variable of its rate
//!   (`<reaction> = kinetic law`), which the equations of its species use;
//!   the local parameters of a kinetic law become variables
//!   `<reaction>_<parameter>` and a species reference with an id a variable
//!   of its stoichiometry
//! - a kinetic law is multiplied with the stoichiometry (no factor for 1),
//!   subtracted for a reactant and added for a product which is no boundary
//!   species, and the sum is multiplied with the conversion factor of the
//!   species or of the model and divided by the compartment for a species in
//!   concentration
//! - a species in concentration whose compartment changes in time and which
//!   no rule determines gets a second variable `<species>_amount` with the
//!   reaction terms and the equation `species = amount / compartment`: SBML
//!   keeps the amount when the size changes
//! - `rateOf(x)` is replaced by the right-hand side of the equation of `x`,
//!   and of such a species by `(dA/dt - S * rateOf(C)) / C`
//! - a model without rate rules, reactions and uses of time gets no variable
//!   of integration, since CellML knows it only from a differential
//!   equation; a model whose formulas use time without one gets the state
//!   `time_state` with `d time_state / d time = 1`
//! - the variables carry their units when the unit annotation of the SBML
//!   model is complete and are all `dimensionless` otherwise, since unset
//!   SBML units are unknown and not dimensionless
//!
//! What this stage does not convert is refused, so that the python converter
//! takes the model instead of a conversion writing something else: an
//! algebraic rule, an event and an initial assignment.

use crate::eval::Start;
use crate::events::{self, Event};
use crate::math::{self, Functions, MathError, Names};
use crate::units::{DIMENSIONLESS, Units, is_annotated};
use cellml::{Component, Interface, Node, Operator, Reset, Variable};
use sbml::math::{Node as Sbml, Op};
use sbml::{Document, Model, Rule, Species, SpeciesReference};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

/// The name of the single component which holds the model.
pub const COMPONENT: &str = "sbml";

/// The name of the variable of integration, unless an element of the model
/// has that id.
pub const TIME: &str = "time";

/// A model the conversion does not write.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum ConvertError {
    /// A formula which has no counterpart in CellML.
    #[error("{0}")]
    Math(#[from] MathError),
    /// An algebraic rule, which needs the variable it determines and a
    /// solution at the start.
    #[error("an algebraic rule is not converted")]
    AlgebraicRule,
}

/// A converted model and what the conversion has to say about it.
#[derive(Debug, Clone)]
pub struct Conversion {
    /// The CellML model.
    pub model: cellml::Model,
    /// The warnings of the conversion, in the order they were made.
    pub warnings: Vec<String>,
}

/// The variable of the amount of a species in concentration.
#[derive(Debug, Clone)]
struct Amount {
    /// The name of the variable of the amount.
    variable: String,
    /// The compartment of the species.
    compartment: String,
}

/// The formulas of a model, with the variables of the local parameters and
/// of the amounts and without `rateOf`.
#[derive(Debug, Default)]
struct Formulas {
    /// The right-hand side by the target of an assignment rule, in the order
    /// of the document.
    assignment_rules: Vec<(String, Sbml)>,
    /// The formula of every initial assignment, by the symbol it computes.
    initial_assignments: Vec<(String, Sbml)>,
    /// The right-hand side of `d x / d time` by the target of a rate rule.
    rate_rules: Vec<(String, Sbml)>,
    /// The right-hand side of `d x / d time` from the reactions, by species
    /// or by the variable of its amount.
    reaction_terms: Vec<(String, Sbml)>,
    /// The rate of every reaction with a kinetic law.
    rates: Vec<(String, Sbml)>,
    /// The variable of every local parameter, by reaction and parameter.
    local_ids: HashMap<String, HashMap<String, String>>,
    /// The variable of the amount by species.
    amounts: Vec<(String, Amount)>,
    /// The name of the variable of integration.
    time_id: String,
    /// The state of a model whose formulas use time without a differential
    /// equation, which integrates it.
    time_state: Option<String>,
    /// The events of the model, which become the resets of the component.
    events: Vec<Event>,
}

impl Formulas {
    /// The ids which an assignment rule computes.
    fn assigned(&self) -> HashSet<&str> {
        self.assignment_rules
            .iter()
            .map(|(id, _)| id.as_str())
            .collect()
    }

    /// The right-hand side of `d x / d time` by id, what `rateOf(x)` stands
    /// for; the concentration `S = A / C` of a species with a variable of
    /// its amount has the rate `(dA/dt - S * rateOf(C)) / C`.
    fn derivatives(&self) -> HashMap<String, Sbml> {
        let mut derivatives: HashMap<String, Sbml> = self
            .rate_rules
            .iter()
            .chain(self.reaction_terms.iter())
            .map(|(id, formula)| (id.clone(), formula.clone()))
            .collect();
        for (species, amount) in &self.amounts {
            let compartment = Sbml::Symbol(amount.compartment.clone());
            let dilution = apply(
                Op::Times,
                vec![
                    Sbml::Symbol(species.clone()),
                    apply(Op::RateOf, vec![compartment.clone()]),
                ],
            );
            let rate = self
                .reaction_terms
                .iter()
                .find(|(id, _)| *id == amount.variable)
                .map_or_else(|| Sbml::number(0.0), |(_, formula)| formula.clone());
            derivatives.insert(
                species.clone(),
                apply(
                    Op::Divide,
                    vec![apply(Op::Minus, vec![rate, dilution]), compartment],
                ),
            );
        }
        derivatives
    }
}

/// The values of an SBML model at the start, which CellML needs as numbers.
#[derive(Debug, Default)]
struct Values {
    /// The value of every quantity an initial assignment computes.
    initial: HashMap<String, f64>,
    /// The size of every compartment at the start, which converts the
    /// initial value of a species; `None` when the model does not determine
    /// it.
    sizes: HashMap<String, Option<f64>>,
}

/// Evaluates what the SBML model computes at the start.
///
/// CellML has no initial assignment, so the conversion evaluates every one
/// of them to the value of its quantity; one which cannot be evaluated (a
/// delay, a value which needs itself, a symbol which is no quantity) is not
/// converted, with a warning, as in the python converter. The size of a
/// compartment at the start is the value of its assignment rule when a rule
/// gives it, since the initial values of its species are converted with it.
fn evaluate(
    model: &Model,
    formulas: &Formulas,
    assigned: &HashSet<&str>,
    warnings: &mut Vec<String>,
) -> Values {
    let mut start = Start::new(
        model,
        &formulas.initial_assignments,
        &formulas.assignment_rules,
        &formulas.rates,
        local_values(model, formulas),
    );
    let mut values = Values::default();
    for (symbol, _) in &formulas.initial_assignments {
        match start.value(symbol) {
            Ok(value) => {
                values.initial.insert(symbol.clone(), value);
            }
            Err(error) => warnings.push(format!(
                "the initial assignment of '{symbol}' is not converted: {error}"
            )),
        }
    }
    for compartment in &model.compartments {
        let size = if assigned.contains(compartment.id.as_str()) {
            start.value(&compartment.id).ok()
        } else {
            values
                .initial
                .get(&compartment.id)
                .copied()
                .or(compartment.size)
        };
        values.sizes.insert(compartment.id.clone(), size);
    }
    values
}

/// The value of the variable of every local parameter of a kinetic law,
/// which the formula of the rate of a reaction reads.
fn local_values(model: &Model, formulas: &Formulas) -> HashMap<String, f64> {
    let mut values = HashMap::new();
    for reaction in &model.reactions {
        let Some(law) = &reaction.kinetic_law else {
            continue;
        };
        let Some(ids) = formulas.local_ids.get(&reaction.id) else {
            continue;
        };
        for parameter in &law.local_parameters {
            if let Some(variable) = ids.get(&parameter.id) {
                values.insert(variable.clone(), parameter.value.unwrap_or(1.0));
            }
        }
    }
    values
}

/// An operator applied to its arguments, as an SBML formula.
fn apply(op: Op, args: Vec<Sbml>) -> Sbml {
    Sbml::Apply { op, args }
}

/// The CellML model of an SBML document.
///
/// `name` names the CellML model when the SBML model has no id, as the file
/// of the document does in the python converter.
pub fn convert(document: &Document, name: &str) -> Result<Conversion, ConvertError> {
    let model = &document.model;
    refuse_what_is_not_converted(model)?;
    let mut warnings = Vec::new();
    let formulas = collect(model, &mut warnings)?;
    build(document, name, &formulas, &mut warnings)
}

/// Refuses a model with what this stage does not convert, so that the python
/// converter takes it instead.
fn refuse_what_is_not_converted(model: &Model) -> Result<(), ConvertError> {
    if model
        .rules
        .iter()
        .any(|rule| matches!(rule, Rule::Algebraic { .. }))
    {
        return Err(ConvertError::AlgebraicRule);
    }
    Ok(())
}

/// The formulas of the rules and the reactions of a model, with the calls of
/// the function definitions and the `rateOf` symbols expanded.
fn collect(model: &Model, warnings: &mut Vec<String>) -> Result<Formulas, ConvertError> {
    let functions = Functions::new(&model.function_definitions);
    let mut used = element_ids(model);
    let time_id = unique(TIME, &variable_ids(model));
    used.insert(time_id.clone());

    let mut formulas = Formulas {
        time_id,
        ..Formulas::default()
    };
    for rule in &model.rules {
        match rule {
            Rule::Assignment { variable, math, .. } => {
                if let Some(math) = math {
                    formulas
                        .assignment_rules
                        .push((variable.clone(), functions.expand(math)?));
                } else {
                    warnings.push(format!(
                        "the rule for '{variable}' has no mathematics and is ignored"
                    ));
                }
            }
            Rule::Rate { variable, math, .. } => {
                if let Some(math) = math {
                    formulas
                        .rate_rules
                        .push((variable.clone(), functions.expand(math)?));
                } else {
                    warnings.push(format!(
                        "the rule for '{variable}' has no mathematics and is ignored"
                    ));
                }
            }
            Rule::Algebraic { .. } => return Err(ConvertError::AlgebraicRule),
        }
    }
    formulas.events = events::collect(model, &functions, &mut used, warnings)?;
    for assignment in &model.initial_assignments {
        if let Some(math) = &assignment.math {
            formulas
                .initial_assignments
                .push((assignment.symbol.clone(), functions.expand(math)?));
        } else {
            warnings.push(format!(
                "the initial assignment of '{}' has no mathematics and is ignored",
                assignment.symbol
            ));
        }
    }

    // a local parameter is visible in its kinetic law only, and several
    // reactions may have one of the same id: each becomes a variable of its
    // own, `<reaction>_<parameter>`
    for reaction in &model.reactions {
        let Some(law) = &reaction.kinetic_law else {
            continue;
        };
        for parameter in &law.local_parameters {
            let variable = unique(&format!("{}_{}", reaction.id, parameter.id), &used);
            used.insert(variable.clone());
            formulas
                .local_ids
                .entry(reaction.id.clone())
                .or_default()
                .insert(parameter.id.clone(), variable);
        }
    }
    for reaction in &model.reactions {
        let law = reaction
            .kinetic_law
            .as_ref()
            .filter(|law| law.math.is_some());
        let Some(law) = law else {
            warnings.push(format!(
                "the reaction '{}' has no kinetic law with mathematics and is not converted",
                reaction.id
            ));
            continue;
        };
        let math = functions.expand(law.math.as_ref().expect("the law has mathematics"))?;
        let local = formulas
            .local_ids
            .get(&reaction.id)
            .cloned()
            .unwrap_or_default();
        formulas
            .rates
            .push((reaction.id.clone(), rename(&math, &local)));
    }

    let determined: HashSet<&str> = formulas
        .assignment_rules
        .iter()
        .chain(formulas.rate_rules.iter())
        .map(|(id, _)| id.as_str())
        .collect();
    let solved: HashSet<&str> = formulas
        .rate_rules
        .iter()
        .map(|(id, _)| id.as_str())
        .collect();
    let changing = changing(model, &formulas.assignment_rules, &solved);
    formulas.amounts = amounts(model, &determined, &changing, &mut used);
    formulas.reaction_terms = reaction_terms(model, &formulas, warnings);

    // CellML knows the variable of integration only from a differential
    // equation: a model whose formulas use time without one gets a state
    // which integrates it, `d time_state / d time = 1`
    if formulas.rate_rules.is_empty() && formulas.reaction_terms.is_empty() && uses_time(model) {
        let state = unique(&format!("{}_state", formulas.time_id), &used);
        used.insert(state.clone());
        formulas.time_state = Some(state);
    }

    // CellML has no rateOf: every symbol is replaced by the right-hand side
    // of the equation of its variable
    let derivatives = formulas.derivatives();
    let assigned: HashSet<String> = formulas
        .assigned()
        .into_iter()
        .map(ToString::to_string)
        .collect();
    for formula in formulas
        .assignment_rules
        .iter_mut()
        .chain(formulas.rate_rules.iter_mut())
        .chain(formulas.reaction_terms.iter_mut())
        .chain(formulas.rates.iter_mut())
        .chain(formulas.initial_assignments.iter_mut())
    {
        formula.1 = expand_rate_of(&formula.1, &derivatives, &assigned, &[], warnings);
    }
    Ok(formulas)
}

/// The ids of the elements of a model, which a new name may not take.
fn element_ids(model: &Model) -> HashSet<String> {
    let mut ids = variable_ids(model);
    ids.extend(model.id.clone());
    ids.extend(model.unit_definitions.iter().map(|d| d.id.clone()));
    ids.extend(
        model
            .function_definitions
            .iter()
            .map(|definition| definition.id.clone()),
    );
    ids.extend(model.rules.iter().filter_map(rule_id));
    ids.extend(model.events.iter().filter_map(|event| event.id.clone()));
    ids.extend(
        model
            .initial_assignments
            .iter()
            .filter_map(|assignment| assignment.id.clone()),
    );
    for reaction in &model.reactions {
        if let Some(law) = &reaction.kinetic_law {
            ids.extend(law.id.clone());
            ids.extend(law.local_parameters.iter().map(|p| p.id.clone()));
        }
    }
    ids
}

/// The id of a rule, which every kind of rule may have.
fn rule_id(rule: &Rule) -> Option<String> {
    match rule {
        Rule::Assignment { id, .. } | Rule::Rate { id, .. } | Rule::Algebraic { id, .. } => {
            id.clone()
        }
    }
}

/// The ids of the elements which become variables of the component: the
/// compartments, species, parameters, reactions and species references.
fn variable_ids(model: &Model) -> HashSet<String> {
    let mut ids: HashSet<String> = HashSet::new();
    ids.extend(model.compartments.iter().map(|c| c.id.clone()));
    ids.extend(model.species.iter().map(|s| s.id.clone()));
    ids.extend(model.parameters.iter().map(|p| p.id.clone()));
    for reaction in &model.reactions {
        ids.insert(reaction.id.clone());
        for reference in references(reaction) {
            ids.extend(reference.id.clone());
        }
    }
    ids
}

/// The reactants and the products of a reaction, which are its variables of
/// a stoichiometry and the species its rate changes.
fn references(reaction: &sbml::Reaction) -> impl Iterator<Item = &SpeciesReference> {
    reaction.reactants.iter().chain(reaction.products.iter())
}

/// A name which no other name of the model takes, with a numeric suffix.
fn unique(name: &str, used: &HashSet<String>) -> String {
    if !used.contains(name) {
        return name.to_string();
    }
    let mut suffix = 2;
    loop {
        let candidate = format!("{name}_{suffix}");
        if !used.contains(&candidate) {
            return candidate;
        }
        suffix += 1;
    }
}

/// A formula with the symbols of `names` renamed, the local parameters of a
/// kinetic law to their variables.
fn rename(node: &Sbml, names: &HashMap<String, String>) -> Sbml {
    match node {
        Sbml::Symbol(name) => names
            .get(name)
            .map_or_else(|| node.clone(), |renamed| Sbml::Symbol(renamed.clone())),
        Sbml::Apply { op, args } => Sbml::Apply {
            op: op.clone(),
            args: args.iter().map(|arg| rename(arg, names)).collect(),
        },
        Sbml::Piecewise { pieces, otherwise } => Sbml::Piecewise {
            pieces: pieces
                .iter()
                .map(|(value, condition)| (rename(value, names), rename(condition, names)))
                .collect(),
            otherwise: otherwise
                .as_ref()
                .map(|otherwise| Box::new(rename(otherwise, names))),
        },
        Sbml::Lambda { params, body } => Sbml::Lambda {
            params: params.clone(),
            body: Box::new(rename(body, names)),
        },
        other => other.clone(),
    }
}

/// Whether a rule, a kinetic law or an event of the model uses the time
/// symbol.
fn uses_time(model: &Model) -> bool {
    let mut formulas: Vec<&Sbml> = Vec::new();
    for rule in &model.rules {
        match rule {
            Rule::Assignment { math, .. }
            | Rule::Rate { math, .. }
            | Rule::Algebraic { math, .. } => formulas.extend(math.as_ref()),
        }
    }
    for reaction in &model.reactions {
        if let Some(law) = &reaction.kinetic_law {
            formulas.extend(law.math.as_ref());
        }
    }
    for event in &model.events {
        formulas.extend(
            event
                .trigger
                .as_ref()
                .and_then(|trigger| trigger.math.as_ref()),
        );
        formulas.extend(
            event
                .assignments
                .iter()
                .filter_map(|assignment| assignment.math.as_ref()),
        );
    }
    formulas.into_iter().any(has_time)
}

/// Whether a formula uses the time symbol.
fn has_time(node: &Sbml) -> bool {
    match node {
        Sbml::CsymbolTime => true,
        Sbml::Apply { args, .. } => args.iter().any(has_time),
        Sbml::Piecewise { pieces, otherwise } => {
            pieces
                .iter()
                .any(|(value, condition)| has_time(value) || has_time(condition))
                || otherwise.as_ref().is_some_and(|node| has_time(node))
        }
        Sbml::Lambda { body, .. } => has_time(body),
        _ => false,
    }
}

/// The names a formula reads.
fn symbols(node: &Sbml) -> Vec<&str> {
    match node {
        Sbml::Symbol(name) => vec![name.as_str()],
        Sbml::Apply { args, .. } => args.iter().flat_map(symbols).collect(),
        Sbml::Piecewise { pieces, otherwise } => pieces
            .iter()
            .flat_map(|(value, condition)| symbols(value).into_iter().chain(symbols(condition)))
            .chain(
                otherwise
                    .as_ref()
                    .map(|node| symbols(node))
                    .unwrap_or_default(),
            )
            .collect(),
        Sbml::Lambda { body, .. } => symbols(body),
        _ => Vec::new(),
    }
}

/// The ids of the variables which change in time: the targets of rate rules,
/// the species the reactions change, the rates of the reactions, the targets
/// of assignment rules which use time or a variable which changes, and the
/// concentration of a species in a compartment which changes.
///
/// An assignment rule of constants, a volume from a body weight for example,
/// does not change its target.
fn changing(
    model: &Model,
    assignment_rules: &[(String, Sbml)],
    solved: &HashSet<&str>,
) -> HashSet<String> {
    let mut changing: HashSet<String> = solved.iter().map(|id| (*id).to_string()).collect();
    for reaction in &model.reactions {
        changing.insert(reaction.id.clone());
        for reference in references(reaction) {
            if !boundary(model, &reference.species) {
                changing.insert(reference.species.clone());
            }
        }
    }
    let names: Vec<(&str, Vec<&str>)> = assignment_rules
        .iter()
        .map(|(id, formula)| (id.as_str(), symbols(formula)))
        .collect();
    for (id, formula) in assignment_rules {
        if has_time(formula) {
            changing.insert(id.clone());
        }
    }
    loop {
        let size = changing.len();
        for (id, reads) in &names {
            if reads.iter().any(|name| changing.contains(*name)) {
                changing.insert((*id).to_string());
            }
        }
        for species in &model.species {
            if changing.contains(&species.compartment) && !species.has_only_substance_units {
                changing.insert(species.id.clone());
            }
        }
        if changing.len() == size {
            return changing;
        }
    }
}

/// Whether the species is a boundary species, which the reactions do not
/// change.
fn boundary(model: &Model, species: &str) -> bool {
    model
        .species
        .iter()
        .find(|candidate| candidate.id == species)
        .is_some_and(|species| species.boundary_condition)
}

/// The species in concentration which need a variable of their amount: the
/// ones in a compartment which changes in time and which no rule determines.
///
/// SBML keeps the amount of a species when the size of its compartment
/// changes, so the concentration follows the size.
fn amounts(
    model: &Model,
    determined: &HashSet<&str>,
    changing: &HashSet<String>,
    used: &mut HashSet<String>,
) -> Vec<(String, Amount)> {
    let mut amounts = Vec::new();
    for species in &model.species {
        if species.has_only_substance_units
            || determined.contains(species.id.as_str())
            || !changing.contains(&species.compartment)
        {
            continue;
        }
        let variable = unique(&format!("{}_amount", species.id), used);
        used.insert(variable.clone());
        amounts.push((
            species.id.clone(),
            Amount {
                variable,
                compartment: species.compartment.clone(),
            },
        ));
    }
    amounts
}

/// The rate of change of every species from the rates of its reactions.
///
/// The rate of a reaction is in amount per time; multiplied with the
/// stoichiometry it is subtracted for every reactant and added for every
/// product which is no boundary species, the sum is multiplied with the
/// conversion factor of the species or of the model, and a species in
/// concentration is divided by the size of its compartment. A species with a
/// variable of its amount gets the rate of change of that variable.
fn reaction_terms(
    model: &Model,
    formulas: &Formulas,
    warnings: &mut Vec<String>,
) -> Vec<(String, Sbml)> {
    let converted: HashSet<&str> = formulas.rates.iter().map(|(id, _)| id.as_str()).collect();
    let mut terms: Vec<(String, Vec<(Op, Sbml)>)> = Vec::new();
    for reaction in &model.reactions {
        if !converted.contains(reaction.id.as_str()) {
            continue;
        }
        for (sign, list) in [
            (Op::Minus, &reaction.reactants),
            (Op::Plus, &reaction.products),
        ] {
            for reference in list {
                if boundary(model, &reference.species) {
                    continue;
                }
                let factor = stoichiometry(&reaction.id, reference, warnings);
                let rate = Sbml::Symbol(reaction.id.clone());
                let term = match factor {
                    Some(factor) => apply(Op::Times, vec![factor, rate]),
                    None => rate,
                };
                match terms.iter_mut().find(|(id, _)| *id == reference.species) {
                    Some((_, species)) => species.push((sign.clone(), term)),
                    None => terms.push((reference.species.clone(), vec![(sign.clone(), term)])),
                }
            }
        }
    }

    let mut result = Vec::new();
    for (id, signed) in terms {
        let Some(species) = model.species.iter().find(|species| species.id == id) else {
            continue;
        };
        let mut formula = signed_sum(signed);
        // the conversion factor of the species, else of the model, converts
        // the extent of the reactions into the amount of the species
        let factor = species
            .conversion_factor
            .clone()
            .or_else(|| model.conversion_factor.clone());
        if let Some(factor) = factor {
            formula = apply(Op::Times, vec![Sbml::Symbol(factor), formula]);
        }
        if let Some((_, amount)) = formulas.amounts.iter().find(|(species, _)| *species == id) {
            result.push((amount.variable.clone(), formula));
            continue;
        }
        if !species.has_only_substance_units {
            let per_size = apply(
                Op::Divide,
                vec![Sbml::number(1.0), Sbml::Symbol(species.compartment.clone())],
            );
            formula = apply(Op::Times, vec![per_size, formula]);
        }
        result.push((id, formula));
    }
    result
}

/// The factor of the kinetic law for a species reference, `None` for 1.
///
/// A stoichiometry which is not set is 1 in level 1 and 2 and unknown in
/// level 3, where 1 is used with a warning; the reader reads the default of
/// the level, so an unset stoichiometry is one of level 3.
fn stoichiometry(
    reaction: &str,
    reference: &SpeciesReference,
    warnings: &mut Vec<String>,
) -> Option<Sbml> {
    if let Some(id) = &reference.id {
        return Some(Sbml::Symbol(id.clone()));
    }
    match reference.stoichiometry {
        None => {
            warnings.push(format!(
                "the stoichiometry of '{}' in the reaction '{reaction}' is not set, using 1",
                reference.species
            ));
            None
        }
        Some(1.0) => None,
        Some(value) => Some(Sbml::number(value)),
    }
}

/// The sum of the signed terms, `- a + b - c`.
fn signed_sum(terms: Vec<(Op, Sbml)>) -> Sbml {
    let mut sum: Option<Sbml> = None;
    for (sign, term) in terms {
        sum = Some(match sum {
            None => match sign {
                Op::Minus => apply(Op::Minus, vec![term]),
                _ => term,
            },
            Some(left) => apply(sign, vec![left, term]),
        });
    }
    sum.unwrap_or_else(|| Sbml::number(0.0))
}

/// A formula with its `rateOf` symbols replaced by the rates they stand for.
///
/// `rateOf(x)` becomes the right-hand side of the differential equation of
/// `x`, and 0 when `x` has none; it stays, with a warning, when the rate of
/// `x` depends on itself or an assignment rule sets `x`, which SBML does not
/// allow, and the validation of the CellML reports it then.
fn expand_rate_of(
    node: &Sbml,
    derivatives: &HashMap<String, Sbml>,
    assigned: &HashSet<String>,
    path: &[String],
    warnings: &mut Vec<String>,
) -> Sbml {
    if let Sbml::Apply {
        op: Op::RateOf,
        args,
    } = node
        && let [Sbml::Symbol(target)] = args.as_slice()
    {
        if path.contains(target) {
            warnings.push(format!(
                "rateOf({target}) is not converted, the rate of '{target}' depends on itself"
            ));
            return node.clone();
        }
        if assigned.contains(target) {
            warnings.push(format!(
                "rateOf({target}) is not converted, '{target}' is computed by a rule"
            ));
            return node.clone();
        }
        let rate = derivatives
            .get(target)
            .cloned()
            .unwrap_or_else(|| Sbml::number(0.0));
        let mut deeper = path.to_vec();
        deeper.push(target.clone());
        return expand_rate_of(&rate, derivatives, assigned, &deeper, warnings);
    }
    match node {
        Sbml::Apply { op, args } => Sbml::Apply {
            op: op.clone(),
            args: args
                .iter()
                .map(|arg| expand_rate_of(arg, derivatives, assigned, path, warnings))
                .collect(),
        },
        Sbml::Piecewise { pieces, otherwise } => Sbml::Piecewise {
            pieces: pieces
                .iter()
                .map(|(value, condition)| {
                    (
                        expand_rate_of(value, derivatives, assigned, path, warnings),
                        expand_rate_of(condition, derivatives, assigned, path, warnings),
                    )
                })
                .collect(),
            otherwise: otherwise.as_ref().map(|otherwise| {
                Box::new(expand_rate_of(
                    otherwise,
                    derivatives,
                    assigned,
                    path,
                    warnings,
                ))
            }),
        },
        other => other.clone(),
    }
}

/// The units of the variables of a model with a complete unit annotation.
///
/// Units which are not set are unknown in SBML and not dimensionless, so the
/// units are converted for all variables or for none: a model in which some
/// variables had units and the others were dimensionless would state units
/// which the SBML model does not have.
fn variable_units(
    model: &Model,
    level: u32,
    units: &mut Units,
    formulas: &Formulas,
    has_time: bool,
    warnings: &mut Vec<String>,
) -> HashMap<String, String> {
    let mut of: Vec<(String, Option<String>)> = Vec::new();
    if has_time {
        let time = units.time(model);
        of.push((formulas.time_id.clone(), time.clone()));
        if let Some(state) = &formulas.time_state {
            of.push((state.clone(), time));
        }
    }
    for compartment in &model.compartments {
        of.push((
            compartment.id.clone(),
            units.of_compartment(model, compartment),
        ));
    }
    for parameter in &model.parameters {
        of.push((
            parameter.id.clone(),
            units.of_parameter(parameter.units.as_deref()),
        ));
    }
    for species in &model.species {
        of.push((species.id.clone(), units.of_species(model, species)));
        if let Some((_, amount)) = formulas.amounts.iter().find(|(id, _)| *id == species.id) {
            of.push((amount.variable.clone(), units.of_amount(model, species)));
        }
    }
    for reaction in &model.reactions {
        let Some(law) = &reaction.kinetic_law else {
            continue;
        };
        let Some(ids) = formulas.local_ids.get(&reaction.id) else {
            continue;
        };
        for parameter in &law.local_parameters {
            let Some(variable) = ids.get(&parameter.id) else {
                continue;
            };
            of.push((
                variable.clone(),
                units.of_parameter(parameter.units.as_deref()),
            ));
        }
        // a stoichiometry has no units
        for reference in references(reaction) {
            if let Some(id) = &reference.id {
                of.push((id.clone(), Some(DIMENSIONLESS.to_string())));
            }
        }
    }
    for (id, _) in &formulas.rates {
        of.push((id.clone(), units.of_reaction(model)));
    }

    let mut missing: Vec<&str> = of
        .iter()
        .filter(|(_, name)| name.is_none())
        .map(|(id, _)| id.as_str())
        .collect();
    if missing.is_empty() {
        return of
            .into_iter()
            .filter_map(|(id, name)| name.map(|name| (id, name)))
            .collect();
    }
    if is_annotated(model, level) {
        missing.sort_unstable();
        warnings.push(format!(
            "the units of the variables are not converted, the unit annotation is incomplete: {} have no units",
            missing.join(", ")
        ));
    }
    HashMap::new()
}

/// The CellML model of the collected formulas.
fn build(
    document: &Document,
    name: &str,
    formulas: &Formulas,
    warnings: &mut Vec<String>,
) -> Result<Conversion, ConvertError> {
    let model = &document.model;
    let mut units = Units::new(model, document.level);
    // CellML knows the variable of integration only from a differential
    // equation, an unused one has an unknown type: the model is algebraic
    let has_time =
        !formulas.rate_rules.is_empty() || !formulas.reaction_terms.is_empty() || uses_time(model);
    let of = variable_units(
        model,
        document.level,
        &mut units,
        formulas,
        has_time,
        warnings,
    );
    let mut component = Component {
        name: COMPONENT.to_string(),
        import: None,
        variables: Vec::new(),
        math: Vec::new(),
        units: Vec::new(),
        resets: Vec::new(),
    };
    let assigned = formulas.assigned();
    let values = evaluate(model, formulas, &assigned, warnings);
    let names = Names {
        variable: &|id: &str| id.to_string(),
        time: &formulas.time_id,
    };

    if has_time {
        add(&mut component, &formulas.time_id, None, &of);
    }
    if let Some(state) = &formulas.time_state {
        add(&mut component, state, Some(0.0), &of);
    }
    add_compartments(&mut component, model, &assigned, &values, &of, warnings);
    for parameter in &model.parameters {
        let value = if assigned.contains(parameter.id.as_str()) {
            None
        } else {
            let stated = values
                .initial
                .get(&parameter.id)
                .copied()
                .or(parameter.value);
            Some(initial_value(&parameter.id, stated, 1.0, warnings))
        };
        add(&mut component, &parameter.id, value, &of);
    }
    add_species(
        &mut component,
        model,
        &assigned,
        formulas,
        &values,
        &of,
        warnings,
    );
    for reaction in &model.reactions {
        let Some(law) = &reaction.kinetic_law else {
            continue;
        };
        let Some(ids) = formulas.local_ids.get(&reaction.id) else {
            continue;
        };
        for parameter in &law.local_parameters {
            let Some(variable) = ids.get(&parameter.id) else {
                continue;
            };
            let value = initial_value(variable, parameter.value, 1.0, warnings);
            add(&mut component, variable, Some(value), &of);
        }
    }
    for reaction in &model.reactions {
        for reference in references(reaction) {
            let Some(id) = &reference.id else {
                continue;
            };
            let value = if assigned.contains(id.as_str()) {
                None
            } else {
                let stated = values.initial.get(id).copied().or(reference.stoichiometry);
                Some(initial_value(id, stated, 1.0, warnings))
            };
            add(&mut component, id, value, &of);
        }
    }
    for (id, _) in &formulas.rates {
        add(&mut component, id, None, &of);
    }
    for event in &formulas.events {
        add(&mut component, &event.trigger, None, &of);
    }

    for (id, formula) in &formulas.assignment_rules {
        let equation = math::expression(formula, &names, &mut units)?;
        component.math.push(assignment(id, equation));
    }
    for (species, amount) in &formulas.amounts {
        let formula = apply(
            Op::Divide,
            vec![
                Sbml::Symbol(amount.variable.clone()),
                Sbml::Symbol(amount.compartment.clone()),
            ],
        );
        let equation = math::expression(&formula, &names, &mut units)?;
        component.math.push(assignment(species, equation));
    }
    if let Some(state) = &formulas.time_state {
        let one = math::expression(&Sbml::number(1.0), &names, &mut units)?;
        component
            .math
            .push(differential(state, &formulas.time_id, one));
    }
    for (id, formula) in formulas
        .rate_rules
        .iter()
        .chain(formulas.reaction_terms.iter())
    {
        let equation = math::expression(formula, &names, &mut units)?;
        component
            .math
            .push(differential(id, &formulas.time_id, equation));
    }
    for (id, formula) in &formulas.rates {
        let equation = math::expression(formula, &names, &mut units)?;
        component.math.push(assignment(id, equation));
    }
    for event in &formulas.events {
        let condition = events::trigger_equation(&event.condition);
        let equation = math::expression(&condition, &names, &mut units)?;
        component.math.push(assignment(&event.trigger, equation));
    }
    add_resets(&mut component, formulas, &names, &mut units, warnings)?;
    let states: HashSet<&str> = formulas
        .rate_rules
        .iter()
        .chain(formulas.reaction_terms.iter())
        .map(|(id, _)| id.as_str())
        .collect();
    add_non_finite_equations(&mut component, &states, warnings);

    warnings.extend(units.warnings().iter().cloned());
    Ok(Conversion {
        model: cellml::Model {
            name: model.id.clone().unwrap_or_else(|| name.to_string()),
            units: units.definitions().to_vec(),
            components: vec![component],
            connections: Vec::new(),
            encapsulation: Vec::new(),
            imports: Vec::new(),
        },
        warnings: std::mem::take(warnings),
    })
}

/// Adds the resets of the events of the model.
///
/// Every assignment of an event becomes a reset of its variable which fires
/// when the variable of the trigger of the event reaches 1; SBML fires the
/// event of the highest priority first and CellML applies the reset of the
/// lowest order, so the resets are ordered by the priority of their event.
/// The assignment of a species with a variable of its amount sets the
/// amount, which is the state of the CellML model.
fn add_resets(
    component: &mut Component,
    formulas: &Formulas,
    names: &Names,
    units: &mut Units,
    warnings: &mut Vec<String>,
) -> Result<(), ConvertError> {
    let variables: HashSet<&str> = component
        .variables
        .iter()
        .map(|variable| variable.name.as_str())
        .collect();
    let mut events: Vec<&Event> = formulas.events.iter().collect();
    events.sort_by(|one, other| {
        other
            .priority
            .partial_cmp(&one.priority)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let mut order = 0;
    for event in events {
        for (id, formula) in &event.assignments {
            let amount = formulas
                .amounts
                .iter()
                .find(|(species, _)| species == id)
                .map(|(_, amount)| amount);
            let (variable, value) = match amount {
                Some(amount) => (
                    amount.variable.clone(),
                    apply(
                        Op::Times,
                        vec![formula.clone(), Sbml::Symbol(amount.compartment.clone())],
                    ),
                ),
                None => (id.clone(), formula.clone()),
            };
            if !variables.contains(variable.as_str()) {
                warnings.push(format!(
                    "the event '{}' assigns '{id}', which is no variable of the model: the assignment is not converted",
                    event.id
                ));
                continue;
            }
            let test = math::expression(&Sbml::number(1.0), names, units)?;
            let reset = math::expression(&value, names, units)?;
            component.resets.push(Reset {
                variable: variable.clone(),
                test_variable: event.trigger.clone(),
                order,
                test_value: Some(assignment(&event.trigger, test)),
                reset_value: Some(assignment(&variable, reset)),
            });
            order += 1;
        }
    }
    Ok(())
}

/// Adds a variable to the component, with its units and its initial value;
/// a variable an equation computes has none.
fn add(component: &mut Component, name: &str, value: Option<f64>, of: &HashMap<String, String>) {
    // a value of `-0` is the zero of the model
    let value = value.map(|value| if value == 0.0 { 0.0 } else { value });
    component.variables.push(Variable {
        name: name.to_string(),
        units: of
            .get(name)
            .cloned()
            .unwrap_or_else(|| DIMENSIONLESS.to_string()),
        initial_value: value.map(cellml::number_text),
        interface: Interface::None,
        public_interface: cellml::Direction::None,
        private_interface: cellml::Direction::None,
    });
}

/// Adds the compartments as variables and gives their size at the start,
/// which converts the initial values of their species.
fn add_compartments(
    component: &mut Component,
    model: &Model,
    assigned: &HashSet<&str>,
    values: &Values,
    of: &HashMap<String, String>,
    warnings: &mut Vec<String>,
) {
    for compartment in &model.compartments {
        let size = values
            .sizes
            .get(&compartment.id)
            .copied()
            .unwrap_or_default();
        if assigned.contains(compartment.id.as_str()) {
            // an equation computes the size, which must have no initial
            // value; the size at the start converts the initial values of
            // the species of the compartment
            add(component, &compartment.id, None, of);
        } else {
            let value = initial_value(&compartment.id, size, 1.0, warnings);
            add(component, &compartment.id, Some(value), of);
        }
    }
}

/// Adds the species as variables.
///
/// A species with `hasOnlySubstanceUnits` is a variable in amount and every
/// other species one in concentration; an initial value given in the other
/// quantity is converted with the size of the compartment. A species an
/// assignment rule sets has no initial value, and one with a variable of its
/// amount has the initial amount on that variable.
fn add_species(
    component: &mut Component,
    model: &Model,
    assigned: &HashSet<&str>,
    formulas: &Formulas,
    values: &Values,
    of: &HashMap<String, String>,
    warnings: &mut Vec<String>,
) {
    for species in &model.species {
        let amount = formulas
            .amounts
            .iter()
            .find(|(id, _)| *id == species.id)
            .map(|(_, amount)| amount);
        let in_amount = species.has_only_substance_units || amount.is_some();
        let initial = if assigned.contains(species.id.as_str()) {
            None
        } else if let Some(value) = values.initial.get(&species.id).copied() {
            // the initial assignment gives the quantity of the species,
            // which is its concentration unless it has only substance units
            Some(if in_amount && !species.has_only_substance_units {
                value * size(species, &values.sizes, warnings)
            } else {
                value
            })
        } else if let Some(value) = species.initial_amount {
            Some(if in_amount {
                value
            } else {
                value / size(species, &values.sizes, warnings)
            })
        } else if let Some(value) = species.initial_concentration {
            Some(if in_amount {
                value * size(species, &values.sizes, warnings)
            } else {
                value
            })
        } else {
            // a species without an initial amount or concentration has none
            // in SBML; a simulator of the model starts it at zero
            Some(initial_value(&species.id, None, 0.0, warnings))
        };
        match amount {
            Some(amount) => {
                add(component, &species.id, None, of);
                add(component, &amount.variable, initial, of);
            }
            None => add(component, &species.id, initial, of),
        }
    }
}

/// The size of the compartment of a species, for the conversion of its
/// initial value; 1 when the size is not known, with a warning.
fn size(
    species: &Species,
    sizes: &HashMap<String, Option<f64>>,
    warnings: &mut Vec<String>,
) -> f64 {
    match sizes.get(&species.compartment) {
        Some(Some(size)) if size.is_finite() => *size,
        _ => {
            warnings.push(format!(
                "the size of the compartment '{}' is not set, using 1 to convert the initial value of '{}'",
                species.compartment, species.id
            ));
            1.0
        }
    }
}

/// An initial value which is not set, replaced by the value a simulator of
/// the SBML model takes, with a warning.
fn initial_value(name: &str, value: Option<f64>, default: f64, warnings: &mut Vec<String>) -> f64 {
    match value {
        Some(value) => value,
        None => {
            warnings.push(format!(
                "the initial value of '{name}' is not set, using {}",
                cellml::number_text(default)
            ));
            default
        }
    }
}

/// Replaces an infinite and a NaN initial value by an equation: the initial
/// value of CellML is a real number or a variable, and a state keeps it,
/// which CellML cannot express.
fn add_non_finite_equations(
    component: &mut Component,
    states: &HashSet<&str>,
    warnings: &mut Vec<String>,
) {
    let mut equations = Vec::new();
    for variable in &mut component.variables {
        let value = variable
            .initial_value
            .as_deref()
            .and_then(|value| value.parse::<f64>().ok());
        let Some(value) = value.filter(|value| !value.is_finite()) else {
            continue;
        };
        if states.contains(variable.name.as_str()) {
            warnings.push(format!(
                "the initial value of the state '{}' is {}, which CellML cannot express",
                variable.name,
                cellml::number_text(value)
            ));
            continue;
        }
        variable.initial_value = None;
        equations.push(assignment(
            &variable.name,
            if value.is_nan() {
                Node::Constant(cellml::Constant::NotANumber)
            } else if value.is_sign_negative() {
                Node::Apply {
                    operator: Operator::Other("minus".to_string()),
                    arguments: vec![Node::Constant(cellml::Constant::Infinity)],
                }
            } else {
                Node::Constant(cellml::Constant::Infinity)
            },
        ));
    }
    component.math.extend(equations);
}

/// The equation `variable = expression`.
fn assignment(variable: &str, expression: Node) -> Node {
    Node::Apply {
        operator: Operator::Eq,
        arguments: vec![Node::Identifier(variable.to_string()), expression],
    }
}

/// The equation `d variable / d time = expression`.
fn differential(variable: &str, time: &str, expression: Node) -> Node {
    Node::Apply {
        operator: Operator::Eq,
        arguments: vec![
            Node::Derivative {
                variable: time.to_string(),
                degree: 1,
                expression: Box::new(Node::Identifier(variable.to_string())),
            },
            expression,
        ],
    }
}
