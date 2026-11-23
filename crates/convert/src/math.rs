//! The mathematics of a CellML component as the mathematics of SBML.
//!
//! The two are content MathML, so an operator keeps its element: the
//! conversion maps the variables to the ids of their quantities, the units
//! of a number to the id of its unit definition, the variable of
//! integration to the `csymbol` of time and a derivative inside an
//! expression to the `csymbol` `rateOf` of SBML level 3 version 2. An
//! operator which SBML does not have is refused, so that nothing is
//! written which a simulator reads as something else.

use crate::ids::Ids;
use crate::units::UnitIds;
use cellml::{Model, Node, Operator};
use sbml::{Constant as SbmlConstant, Math};
use thiserror::Error;

/// A failure to convert the mathematics of a component.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum MathError {
    /// An operator SBML level 3 version 2 does not have.
    #[error("operator '{0}' has no counterpart in SBML")]
    Operator(String),
    /// An element of MathML the converter does not write.
    #[error("element '{0}' has no counterpart in SBML")]
    Element(String),
    /// Units which the model does not define and which are no base units
    /// of SBML.
    #[error("units '{0}' are neither defined by the model nor units of SBML")]
    Units(String),
    /// A variable which is in no component of the model.
    #[error("variable '{variable}' is not a variable of component '{component}'")]
    Variable {
        /// The name of the variable.
        variable: String,
        /// The name of the component the expression is in.
        component: String,
    },
    /// A derivative of an expression which is no variable, or of an order
    /// SBML cannot express.
    #[error("the derivative of '{0}' has no counterpart in SBML")]
    Derivative(String),
}

/// Every operator of the MathML of SBML level 3 version 2.
const OPERATORS: &[&str] = &[
    "abs",
    "and",
    "arccos",
    "arccosh",
    "arccot",
    "arccoth",
    "arccsc",
    "arccsch",
    "arcsec",
    "arcsech",
    "arcsin",
    "arcsinh",
    "arctan",
    "arctanh",
    "ceiling",
    "cos",
    "cosh",
    "cot",
    "coth",
    "csc",
    "csch",
    "divide",
    "eq",
    "exp",
    "factorial",
    "floor",
    "geq",
    "gt",
    "implies",
    "leq",
    "ln",
    "log",
    "lt",
    "max",
    "min",
    "minus",
    "neq",
    "not",
    "or",
    "plus",
    "power",
    "quotient",
    "rem",
    "root",
    "sec",
    "sech",
    "sin",
    "sinh",
    "tan",
    "tanh",
    "times",
    "xor",
];

/// The operators of MathML which take any number of arguments: with one
/// argument the value of such an operator is the argument itself.
const N_ARY: [&str; 5] = ["plus", "times", "and", "or", "xor"];

/// What the mathematics of a model is written with: the ids of the
/// quantities, the ids of the units and the variable of integration.
#[derive(Debug, Clone, Copy)]
pub struct Context<'a> {
    /// The model the component belongs to.
    pub model: &'a Model,
    /// The quantities of the model.
    pub ids: &'a Ids,
    /// The ids of the unit definitions.
    pub units: &'a UnitIds,
    /// The quantity of the variable of integration, `None` for a model
    /// without a derivative.
    pub voi: Option<usize>,
}

impl<'a> Context<'a> {
    /// The quantity of a variable of a component by its name.
    ///
    /// # Errors
    ///
    /// Returns [`MathError::Variable`] when the component has no variable
    /// of that name.
    pub fn quantity(&self, component: usize, name: &str) -> Result<usize, MathError> {
        self.ids
            .quantity_of(self.model, component, name)
            .ok_or_else(|| MathError::Variable {
                variable: name.to_string(),
                component: self.model.components[component].name.clone(),
            })
    }
}

/// An expression of a component as the mathematics of SBML.
///
/// # Arguments
///
/// * `node` - the expression.
/// * `component` - the index of the component it is in.
/// * `context` - the ids of the model.
///
/// # Errors
///
/// Returns the first [`MathError`] of the expression.
pub fn expression(node: &Node, component: usize, context: Context) -> Result<Math, MathError> {
    match node {
        Node::Number { value, units } => Ok(Math::Number {
            value: *value,
            units: match units {
                Some(name) => Some(
                    context
                        .units
                        .resolve(name)
                        .ok_or_else(|| MathError::Units(name.clone()))?,
                ),
                None => None,
            },
        }),
        Node::Identifier(name) => {
            let quantity = context.quantity(component, name)?;
            if Some(quantity) == context.voi {
                Ok(Math::Time)
            } else {
                Ok(Math::Identifier(context.ids.id(quantity).to_string()))
            }
        }
        Node::Constant(constant) => Ok(Math::Constant(constant_of(*constant))),
        Node::Apply {
            operator,
            arguments,
        } => {
            let name = operator.name();
            if !OPERATORS.contains(&name) {
                return Err(MathError::Operator(name.to_string()));
            }
            // MathML allows an n-ary operator with one argument, which is
            // that argument: `plus(x)` is `x`. The value is written instead
            // of the operator, as `mathml.simplify_operators` writes it on
            // the way to CellML, so that no redundant operator reaches SBML
            if N_ARY.contains(&name) && arguments.len() == 1 {
                return expression(&arguments[0], component, context);
            }
            Ok(Math::Apply {
                operator: name.to_string(),
                arguments: arguments
                    .iter()
                    // a root of the degree two is the square root, which
                    // SBML writes without the degree
                    .filter(|argument| !(name == "root" && is_degree(argument, 2.0)))
                    .map(|argument| expression(argument, component, context))
                    .collect::<Result<Vec<_>, _>>()?,
            })
        }
        Node::Piecewise { pieces, otherwise } => Ok(Math::Piecewise {
            pieces: pieces
                .iter()
                .map(|(value, condition)| {
                    Ok((
                        expression(value, component, context)?,
                        expression(condition, component, context)?,
                    ))
                })
                .collect::<Result<Vec<_>, MathError>>()?,
            otherwise: match otherwise {
                Some(value) => Some(Box::new(expression(value, component, context)?)),
                None => None,
            },
        }),
        Node::Qualifier { name, value } => Ok(Math::Qualifier {
            name: name.clone(),
            value: Box::new(expression(value, component, context)?),
        }),
        // the rate of change of a variable, which SBML writes as `rateOf`
        Node::Derivative {
            variable,
            degree,
            expression: differentiated,
        } => match (*degree, differentiated.as_ref()) {
            (1, Node::Identifier(name)) => {
                let quantity = context.quantity(component, name)?;
                // the variable of integration of the derivative must be
                // the time of the model
                let of = context.quantity(component, variable)?;
                if context.voi.is_some_and(|voi| voi != of) {
                    return Err(MathError::Derivative(name.clone()));
                }
                Ok(Math::RateOf(context.ids.id(quantity).to_string()))
            }
            _ => Err(MathError::Derivative(
                differentiated_name(differentiated).unwrap_or_else(|| "an expression".to_string()),
            )),
        },
        Node::Other(name) => Err(MathError::Element(name.clone())),
    }
}

/// Whether a node is the qualifier `<degree>` of a value.
fn is_degree(node: &Node, value: f64) -> bool {
    match node {
        Node::Qualifier {
            name,
            value: degree,
        } if name == "degree" => {
            matches!(degree.as_ref(), Node::Number { value: number, .. } if *number == value)
        }
        _ => false,
    }
}

/// The name of what is differentiated, for the message of an error.
fn differentiated_name(node: &Node) -> Option<String> {
    match node {
        Node::Identifier(name) => Some(name.clone()),
        _ => None,
    }
}

/// The constant of SBML of a constant of CellML.
fn constant_of(constant: cellml::math::Constant) -> SbmlConstant {
    use cellml::math::Constant as C;
    match constant {
        C::Pi => SbmlConstant::Pi,
        C::Exponentiale => SbmlConstant::Exponentiale,
        C::True => SbmlConstant::True,
        C::False => SbmlConstant::False,
        C::Infinity => SbmlConstant::Infinity,
        C::NotANumber => SbmlConstant::NotANumber,
    }
}

/// The two sides of an equation, `None` for a node which is no equality.
pub fn equality(node: &Node) -> Option<(&Node, &Node)> {
    match node {
        Node::Apply {
            operator: Operator::Eq,
            arguments,
        } if arguments.len() == 2 => Some((&arguments[0], &arguments[1])),
        _ => None,
    }
}

/// Every variable an expression differentiates, by name: the states whose
/// rate the expression uses, which SBML writes as `rateOf`.
pub fn rate_variables(node: &Node, names: &mut Vec<String>) {
    match node {
        Node::Derivative { expression, .. } => {
            if let Node::Identifier(name) = expression.as_ref() {
                names.push(name.clone());
            }
            rate_variables(expression, names);
        }
        Node::Apply { arguments, .. } => {
            for argument in arguments {
                rate_variables(argument, names);
            }
        }
        Node::Piecewise { pieces, otherwise } => {
            for (value, condition) in pieces {
                rate_variables(value, names);
                rate_variables(condition, names);
            }
            if let Some(value) = otherwise {
                rate_variables(value, names);
            }
        }
        Node::Qualifier { value, .. } => rate_variables(value, names),
        Node::Number { .. } | Node::Identifier(_) | Node::Constant(_) | Node::Other(_) => {}
    }
}

/// Every variable an expression uses, by name, in the order of the
/// expression.
pub fn variables(node: &Node, names: &mut Vec<String>) {
    match node {
        Node::Identifier(name) => names.push(name.clone()),
        Node::Apply { arguments, .. } => {
            for argument in arguments {
                variables(argument, names);
            }
        }
        Node::Piecewise { pieces, otherwise } => {
            for (value, condition) in pieces {
                variables(value, names);
                variables(condition, names);
            }
            if let Some(value) = otherwise {
                variables(value, names);
            }
        }
        Node::Qualifier { value, .. } => variables(value, names),
        Node::Derivative {
            variable,
            expression,
            ..
        } => {
            names.push(variable.clone());
            variables(expression, names);
        }
        Node::Number { .. } | Node::Constant(_) | Node::Other(_) => {}
    }
}
