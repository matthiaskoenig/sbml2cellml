//! The events of an SBML model as the resets of a CellML model.
//!
//! CellML applies a reset when its test variable reaches its test value,
//! where SBML fires an event while its trigger holds: the conversion gives
//! every event a variable `<event>_trigger` with the equation
//! `piecewise(1, condition, 0)`, and every assignment of the event becomes a
//! reset of its variable which fires when that variable reaches 1. The
//! conversion of a CellML model to SBML reads the pair back
//! (`crates/convert`, `_condition_of_a_trigger` of the python converter).
//!
//! An event CellML cannot express is not converted, with a warning, as in
//! the python converter: one without a trigger or without an assignment and
//! one whose mathematics uses a factorial, a delay or a `rateOf`, which no
//! CellML model holds. What a reset cannot express, the delay of an event,
//! its priority and the flags of SBML, is kept in the metadata of the
//! conversion (`sbml2cellml.metadata`), which the python package writes
//! from the SBML element of every element of the CellML model.

use std::collections::HashSet;

use sbml::math::{Node as Sbml, Op};
use sbml::{Event as Sbmlevent, Model};

use crate::ids::unique_name;
use crate::math::{Functions, MathError};

/// An SBML event as the resets of a CellML model.
#[derive(Debug, Clone, PartialEq)]
pub struct Event {
    /// The id of the event, for the warnings.
    pub id: String,
    /// The variable which is 1 while the condition holds.
    pub trigger: String,
    /// The condition of the trigger.
    pub condition: Sbml,
    /// The right-hand side of every assignment, by the variable it sets.
    pub assignments: Vec<(String, Sbml)>,
    /// The priority of the event, 0 without one; SBML fires the event of
    /// the highest priority first and CellML applies the reset of the
    /// lowest order.
    pub priority: f64,
}

/// The events of a model which become resets, in the order of the document.
///
/// The calls of the function definitions of the trigger and of the
/// assignments are expanded, and the variable of every trigger is added to
/// `used`.
///
/// Errors:
///     `MathError` when a function definition cannot be expanded.
pub fn collect(
    model: &Model,
    functions: &Functions,
    used: &mut HashSet<String>,
    warnings: &mut Vec<String>,
) -> Result<Vec<Event>, MathError> {
    let mut events = Vec::new();
    for (index, event) in model.events.iter().enumerate() {
        let id = event
            .id
            .clone()
            .unwrap_or_else(|| format!("event_{}", index + 1));
        let Some(event) = convertible(event, &id, functions, warnings)? else {
            continue;
        };
        let (condition, assignments, priority) = event;
        let trigger = unique_name(&format!("{id}_trigger"), used);
        events.push(Event {
            id,
            trigger,
            condition,
            assignments,
            priority,
        });
    }
    Ok(events)
}

/// The condition, the assignments and the priority of an event which
/// becomes resets, `None` for an event which is not converted.
type Convertible = (Sbml, Vec<(String, Sbml)>, f64);

/// What an event becomes, `None` with a warning for one CellML cannot
/// express.
fn convertible(
    event: &Sbmlevent,
    id: &str,
    functions: &Functions,
    warnings: &mut Vec<String>,
) -> Result<Option<Convertible>, MathError> {
    let condition = event
        .trigger
        .as_ref()
        .and_then(|trigger| trigger.math.as_ref());
    let Some(condition) = condition else {
        warnings.push(format!(
            "the event '{id}' has no trigger and is not converted"
        ));
        return Ok(None);
    };
    if event.delay.is_some() {
        warnings.push(format!(
            "the event '{id}' has a delay, which a reset of CellML cannot express: the reset fires when the trigger holds, the delay is kept in the metadata of the conversion"
        ));
    }
    let mut assignments = Vec::new();
    for assignment in &event.assignments {
        if let Some(math) = &assignment.math {
            assignments.push((assignment.variable.clone(), functions.expand(math)?));
        }
    }
    if assignments.is_empty() {
        warnings.push(format!(
            "the event '{id}' assigns nothing and is not converted"
        ));
        return Ok(None);
    }
    let condition = functions.expand(condition)?;
    if let Some(trigger) = &event.trigger {
        if !trigger.initial_value {
            warnings.push(format!(
                "the trigger of the event '{id}' has the initial value 'false', which a reset cannot express: the value is kept in the metadata of the conversion"
            ));
        }
        if !trigger.persistent {
            warnings.push(format!(
                "the trigger of the event '{id}' is not persistent, which a reset cannot express: the flag is kept in the metadata of the conversion"
            ));
        }
    }
    Ok(Some((
        condition,
        assignments,
        priority(event, id, warnings),
    )))
}

/// The name of the first operator of the formulas of an event which has no
/// counterpart in CellML, `None` when the event has none.
///
/// A `rateOf` is replaced by the rate it stands for before this is asked
/// (`model::expand_rate_of`), so one which is left has none either.
#[must_use]
pub fn unsupported(event: &Event) -> Option<&'static str> {
    std::iter::once(&event.condition)
        .chain(event.assignments.iter().map(|(_, math)| math))
        .filter_map(without_counterpart)
        .next()
}

/// The name of the first operator of a formula which has no counterpart in
/// CellML, `None` when the formula has none.
fn without_counterpart(formula: &Sbml) -> Option<&'static str> {
    match formula {
        Sbml::CsymbolDelay => Some("delay"),
        Sbml::CsymbolRateOf => Some("rateOf"),
        Sbml::Apply { op, args } => match op {
            Op::Delay => Some("delay"),
            Op::RateOf => Some("rateOf"),
            Op::Factorial => Some("factorial"),
            _ => args.iter().filter_map(without_counterpart).next(),
        },
        Sbml::Piecewise { pieces, otherwise } => pieces
            .iter()
            .flat_map(|(value, condition)| [value, condition])
            .chain(otherwise.as_deref())
            .filter_map(without_counterpart)
            .next(),
        Sbml::Lambda { body, .. } => without_counterpart(body),
        _ => None,
    }
}

/// The priority of an event, 0 when it has none or none which is a number.
fn priority(event: &Sbmlevent, id: &str, warnings: &mut Vec<String>) -> f64 {
    match &event.priority {
        None => 0.0,
        Some(Sbml::Number { value, .. }) => *value,
        Some(_) => {
            warnings.push(format!(
                "the priority of the event '{id}' is no number, the resets of the model are ordered as if it were 0"
            ));
            0.0
        }
    }
}

/// The equation of the variable of a trigger, `piecewise(1, condition, 0)`.
#[must_use]
pub fn trigger_equation(condition: &Sbml) -> Sbml {
    Sbml::Piecewise {
        pieces: vec![(Sbml::number(1.0), condition.clone())],
        otherwise: Some(Box::new(Sbml::number(0.0))),
    }
}
