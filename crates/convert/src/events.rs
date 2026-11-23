//! The resets of a CellML model as the events of SBML.
//!
//! A reset sets its variable to the reset value when the test variable
//! reaches the test value, which SBML writes as an event: the trigger is
//! the equality of the test variable and the test value, the priority the
//! negated order, since CellML applies the lowest order first and SBML the
//! highest priority, and the event assignment sets the variable.
//!
//! `sbml2cellml` writes the trigger of an SBML event as the variable
//! `piecewise(1, condition, 0)` and resets when it reaches 1; such a reset
//! gives the event the condition itself as its trigger
//! (`condition_of_a_trigger`), which a simulator evaluates as a boolean
//! instead of looking for the root of a step.

use crate::analysis::{Analysis, EquationKind, equation_of};
use crate::ids::Ids;
use crate::math::{Context, equality, expression};
use crate::{ConvertError, other_side};
use cellml::{Model, Node, Reset};
use sbml::{Event, EventAssignment, Math, Trigger};
use std::collections::HashSet;

/// The resets of every component of a model with the component they are
/// written in, in the order of the document.
pub fn resets(model: &Model) -> impl Iterator<Item = (usize, &Reset)> {
    model
        .components
        .iter()
        .enumerate()
        .flat_map(|(component, element)| element.resets.iter().map(move |reset| (component, reset)))
}

/// The quantities a reset sets: they have an initial value and no equation,
/// but a reset writes them, so they are no constants of SBML.
pub fn targets(model: &Model, ids: &Ids) -> HashSet<usize> {
    resets(model)
        .filter_map(|(component, reset)| ids.quantity_of(model, component, &reset.variable))
        .collect()
}

/// The events of the resets of a model.
///
/// # Arguments
///
/// * `analysis` - the equations of the model, for the trigger of a reset
///   which stands for an event of SBML.
/// * `event_ids` - the id of the event of every reset, reserved in the
///   order of [`resets`].
/// * `context` - the model, its quantities and its units.
///
/// # Errors
///
/// Returns a [`ConvertError`] for a reset without the mathematics of its
/// values or with a variable the component does not have.
pub fn events(
    analysis: &Analysis,
    event_ids: &[String],
    context: Context,
) -> Result<Vec<Event>, ConvertError> {
    let model = context.model;
    let mut events = Vec::new();
    for ((component, reset), id) in resets(model).zip(event_ids) {
        let variable = quantity(context, component, reset, &reset.variable)?;
        let test_variable = quantity(context, component, reset, &reset.test_variable)?;
        let test_value = math_of(
            context,
            component,
            reset,
            reset.test_value.as_ref(),
            test_variable,
            "test value",
        )?;
        let reset_value = math_of(
            context,
            component,
            reset,
            reset.reset_value.as_ref(),
            variable,
            "reset value",
        )?;
        let condition = condition_of_a_trigger(analysis, context, test_variable, &test_value);
        let math = match condition {
            Some(condition) => condition,
            None => Math::apply(
                "eq",
                vec![
                    Math::Identifier(context.ids.id(test_variable).to_string()),
                    test_value,
                ],
            ),
        };
        events.push(Event {
            id: id.clone(),
            trigger: Trigger {
                persistent: true,
                initial_value: true,
                math,
            },
            priority: Some(Math::Number {
                value: -f64::from(reset.order),
                units: None,
            }),
            assignments: vec![EventAssignment {
                variable: context.ids.id(variable).to_string(),
                math: reset_value,
            }],
        });
    }
    Ok(events)
}

/// The quantity of a variable a reset names in its component.
fn quantity(
    context: Context,
    component: usize,
    reset: &Reset,
    name: &str,
) -> Result<usize, ConvertError> {
    context
        .ids
        .quantity_of(context.model, component, name)
        .ok_or_else(|| ConvertError::Reset {
            component: context.model.components[component].name.clone(),
            variable: reset.variable.clone(),
            reason: format!("names the variable '{name}', which the component does not have"),
        })
}

/// The expression of a test or a reset value: the mathematics itself or the
/// right side of the equation `variable = expression`, as libcellml and
/// `sbml2cellml` write it.
fn math_of(
    context: Context,
    component: usize,
    reset: &Reset,
    node: Option<&Node>,
    quantity: usize,
    which: &str,
) -> Result<Math, ConvertError> {
    let node = node.ok_or_else(|| ConvertError::Reset {
        component: context.model.components[component].name.clone(),
        variable: reset.variable.clone(),
        reason: format!("has no mathematics of its {which}"),
    })?;
    if let Some((left, right)) = equality(node)
        && matches!(left, Node::Identifier(name)
            if context.ids.quantity_of(context.model, component, name) == Some(quantity))
    {
        return Ok(expression(right, component, context)?);
    }
    Ok(expression(node, component, context)?)
}

/// The condition of a test variable which stands for a trigger.
fn condition_of_a_trigger(
    analysis: &Analysis,
    context: Context,
    test_variable: usize,
    test_value: &Math,
) -> Option<Math> {
    if !matches!(test_value, Math::Number { value, .. } if *value == 1.0) {
        return None;
    }
    let equation = equation_of(analysis, test_variable)?;
    if !matches!(equation.kind, EquationKind::Assignment { .. }) {
        return None;
    }
    let node = &context.model.components[equation.component].math[equation.index];
    let (left, right) = equality(node)?;
    let side = other_side(left, right, |node| {
        matches!(node, Node::Identifier(name)
            if context.ids.quantity_of(context.model, equation.component, name)
                == Some(test_variable))
    });
    let Node::Piecewise { pieces, otherwise } = side else {
        return None;
    };
    let [(value, condition)] = &pieces[..] else {
        return None;
    };
    if !matches!(value, Node::Number { value, .. } if *value == 1.0) {
        return None;
    }
    let otherwise = otherwise.as_deref()?;
    if !matches!(otherwise, Node::Number { value, .. } if *value == 0.0) {
        return None;
    }
    expression(condition, equation.component, context).ok()
}
