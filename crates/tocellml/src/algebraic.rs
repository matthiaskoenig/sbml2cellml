//! The algebraic rules of an SBML model as the implicit equations of CellML.
//!
//! An algebraic rule `0 = formula` of SBML names no variable, where
//! libcellml needs to know which variable an implicit equation determines:
//! [`match_rules`] finds it, a variable of the formula which nothing else
//! determines, with a maximum matching of the rules and their candidates.
//! [`solve`] solves the rules at the start with the secant method, which is
//! the guess of the solver of the simulation and the size of a compartment
//! an algebraic rule determines, as the python converter does with libsbml.

use std::collections::{HashMap, HashSet};

use sbml::Model;
use sbml::math::Node as Sbml;

use crate::eval::Start;

/// The variable every algebraic rule determines and the formula which is
/// zero, in the order the equations are written: a rule follows the rules
/// which determine the other unknowns it uses, since the analyser of
/// libcellml finds a model whose guesses come in another order
/// overconstrained.
///
/// A rule which determines no variable is left out, with a warning.
///
/// Args:
///     model: the SBML model.
///     rules: the formula of every algebraic rule with the name the
///         warnings call it, its id or its place in the document.
///     determined: the ids which an assignment or a rate rule determines.
///     warnings: what the conversion has to say about the model.
pub fn match_rules(
    model: &Model,
    rules: &[(String, Sbml)],
    determined: &HashSet<&str>,
    warnings: &mut Vec<String>,
) -> Vec<(String, Sbml)> {
    let reacting = reacting(model);
    let candidates: Vec<Vec<String>> = rules
        .iter()
        .map(|(_, formula)| {
            let mut names: Vec<String> = formula
                .symbols()
                .into_iter()
                .filter(|name| free(model, name, determined, &reacting))
                .map(ToString::to_string)
                .collect();
            names.sort();
            names.dedup();
            names
        })
        .collect();

    let mut rule_of: HashMap<String, usize> = HashMap::new();
    for (index, (name, _)) in rules.iter().enumerate() {
        let mut seen = HashSet::new();
        if !assign(index, &candidates, &mut rule_of, &mut seen) {
            warnings.push(format!(
                "the algebraic rule {name} determines no variable and is not converted"
            ));
        }
    }

    let variable_of: HashMap<usize, String> = rule_of
        .iter()
        .map(|(name, index)| (*index, name.clone()))
        .collect();
    let mut ordered: Vec<usize> = Vec::new();
    let mut indices: Vec<usize> = variable_of.keys().copied().collect();
    indices.sort_unstable();
    for index in indices {
        visit(
            index,
            &candidates,
            &rule_of,
            &variable_of,
            &mut Vec::new(),
            &mut ordered,
        );
    }
    ordered
        .into_iter()
        .map(|index| (variable_of[&index].clone(), rules[index].1.clone()))
        .collect()
}

/// Gives the rule one of its candidates, moving other rules to free one
/// (the algorithm of Kuhn for a maximum matching).
fn assign(
    rule: usize,
    candidates: &[Vec<String>],
    rule_of: &mut HashMap<String, usize>,
    seen: &mut HashSet<String>,
) -> bool {
    for name in &candidates[rule] {
        if !seen.insert(name.clone()) {
            continue;
        }
        let taken = rule_of.get(name).copied();
        if taken.is_none_or(|other| assign(other, candidates, rule_of, seen)) {
            rule_of.insert(name.clone(), rule);
            return true;
        }
    }
    false
}

/// Puts the rules which determine the other unknowns of a rule before it.
fn visit(
    rule: usize,
    candidates: &[Vec<String>],
    rule_of: &HashMap<String, usize>,
    variable_of: &HashMap<usize, String>,
    path: &mut Vec<usize>,
    ordered: &mut Vec<usize>,
) {
    if ordered.contains(&rule) || path.contains(&rule) {
        return;
    }
    path.push(rule);
    for name in &candidates[rule] {
        if variable_of.get(&rule).is_some_and(|own| own == name) {
            continue;
        }
        if let Some(other) = rule_of.get(name) {
            visit(*other, candidates, rule_of, variable_of, path, ordered);
        }
    }
    path.pop();
    ordered.push(rule);
}

/// The species which the reactions of the model change.
fn reacting(model: &Model) -> HashSet<&str> {
    let mut species = HashSet::new();
    for reaction in &model.reactions {
        for reference in reaction.reactants.iter().chain(reaction.products.iter()) {
            let boundary = model
                .species
                .iter()
                .find(|species| species.id == reference.species)
                .is_some_and(|species| species.boundary_condition);
            if !boundary {
                species.insert(reference.species.as_str());
            }
        }
    }
    species
}

/// Whether an algebraic rule can determine the quantity of an id: a
/// compartment, parameter, species or species reference which is not
/// constant, which no other rule determines and which no reaction changes.
fn free(model: &Model, name: &str, determined: &HashSet<&str>, reacting: &HashSet<&str>) -> bool {
    if determined.contains(name) || reacting.contains(name) {
        return false;
    }
    let constant = model
        .compartments
        .iter()
        .find(|compartment| compartment.id == name)
        .map(|compartment| compartment.constant)
        .or_else(|| {
            model
                .parameters
                .iter()
                .find(|parameter| parameter.id == name)
                .map(|parameter| parameter.constant)
        })
        .or_else(|| {
            model
                .species
                .iter()
                .find(|species| species.id == name)
                .map(|species| species.constant)
        })
        .or_else(|| {
            model
                .reactions
                .iter()
                .flat_map(|reaction| reaction.reactants.iter().chain(reaction.products.iter()))
                .find(|reference| reference.id.as_deref() == Some(name))
                .map(|reference| reference.constant)
        });
    constant == Some(false)
}

/// The value of the variable of every algebraic rule at the start, the root
/// of the formula of the rule.
///
/// The rules are solved in their order, every one with the values of the
/// rules before it, and a rule which cannot be solved keeps the value the
/// model states, with a warning.
pub fn solve(
    rules: &[(String, Sbml)],
    start: &mut Start,
    warnings: &mut Vec<String>,
) -> HashMap<String, f64> {
    let mut solved = HashMap::new();
    for (name, formula) in rules {
        let guess = start.value(name).unwrap_or(1.0);
        let guess = if guess.is_finite() { guess } else { 1.0 };
        match secant(
            &mut |value| {
                start.override_value(name, value);
                start.eval(formula).unwrap_or(f64::NAN)
            },
            guess,
        ) {
            Some(value) => {
                start.override_value(name, value);
                solved.insert(name.clone(), value);
            }
            None => {
                start.override_value(name, guess);
                warnings.push(format!(
                    "the algebraic rule of '{name}' is not solved at the start, the value of the model is the guess of the solver"
                ));
            }
        }
    }
    solved
}

/// A root of a function with the secant method, `None` without convergence.
fn secant(function: &mut dyn FnMut(f64) -> f64, x0: f64) -> Option<f64> {
    let mut x0 = x0;
    let mut x1 = x0 + x0.abs().max(1.0) * 1e-3;
    let mut f0 = function(x0);
    let mut f1 = function(x1);
    for _ in 0..50 {
        if !f0.is_finite() || !f1.is_finite() {
            return None;
        }
        if f1 == 0.0 || (x1 - x0).abs() <= 1e-14 * x1.abs().max(1.0) {
            return Some(x1);
        }
        if f1 == f0 {
            return None;
        }
        let next = x1 - f1 * (x1 - x0) / (f1 - f0);
        (x0, f0) = (x1, f1);
        x1 = next;
        f1 = function(x1);
    }
    None
}
