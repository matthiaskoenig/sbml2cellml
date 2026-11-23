//! The mathematics of an SBML formula as the mathematics of a CellML
//! component.
//!
//! Both are content MathML, so an operator keeps its element. What the
//! conversion changes is what CellML states differently or does not have:
//!
//! - every number carries the CellML name of its units, `dimensionless`
//!   when the formula gives it none, and an infinity or a NaN becomes the
//!   element of MathML, which has no units
//! - the time symbol becomes the variable of integration and the avogadro
//!   symbol the number SBML defines for it
//! - `quotient(a, b)` becomes `floor(a / b)` and `implies(a, b)` becomes
//!   `not a or b`, the two operators CellML does not have; a relation of
//!   more than two arguments becomes the conjunction of its pairs
//!   (`a < b < c` is `and(a < b, b < c)`), and an n-ary operator of less
//!   than two arguments its value (`plus()` is 0, `times(a)` is `a`)
//! - a call of a function definition is expanded, since CellML has no
//!   functions ([`Functions`])
//!
//! `delay` and a `rateOf` which the conversion did not replace are refused:
//! CellML has neither, and nothing is written which a simulator reads as
//! something else.

use crate::units::{AVOGADRO_VALUE, DIMENSIONLESS, Units};
use cellml::{Constant, Node, Operator};
use sbml::FunctionDefinition;
use sbml::math::{Node as Sbml, Op};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

/// A failure to write a formula of SBML as the mathematics of CellML.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum MathError {
    /// The delay symbol, which CellML has no counterpart for.
    #[error("'delay' has no counterpart in CellML")]
    Delay,
    /// A `rateOf` left in a formula: the conversion replaces it by the
    /// right-hand side of the equation of its variable before.
    #[error("'rateOf' is replaced before the mathematics is written")]
    RateOf,
    /// A call of a function the model does not define.
    #[error("the model does not define the function '{0}'")]
    Unknown(String),
    /// A function definition without a lambda, which defines nothing.
    #[error("the function definition '{0}' has no lambda")]
    NoLambda(String),
    /// A function definition which calls itself, directly or over others.
    #[error("the function definition '{0}' calls itself")]
    Recursive(String),
    /// A call with the wrong number of arguments.
    #[error("the function '{name}' takes {parameters} arguments, not {arguments}")]
    Arguments {
        /// The id of the function definition.
        name: String,
        /// How many parameters its lambda has.
        parameters: usize,
        /// How many arguments the call gives.
        arguments: usize,
    },
    /// A lambda in a formula, which is no expression.
    #[error("a lambda is no expression of CellML")]
    Lambda,
    /// A `<math>` element without an expression in it.
    #[error("a formula without mathematics")]
    Empty,
}

/// The function definitions of a model, which a formula calls and the
/// conversion expands: CellML has no functions.
///
/// A definition which calls itself, directly or over other definitions, is
/// found when it is built, so a formula which calls it is refused instead of
/// expanded forever.
#[derive(Debug, Clone, Default)]
pub struct Functions {
    /// The parameters and the body of the lambda of every definition.
    definitions: HashMap<String, (Vec<String>, Sbml)>,
    /// The definitions which are part of a cycle of calls.
    recursive: HashSet<String>,
    /// The definitions which define nothing, since they have no lambda.
    without_lambda: HashSet<String>,
}

impl Functions {
    /// The functions of the definitions of a model.
    ///
    /// A definition without a lambda defines nothing and is kept as such, so
    /// that a call of it says what is wrong with it instead of saying that
    /// the model does not define the function.
    #[must_use]
    pub fn new(definitions: &[FunctionDefinition]) -> Self {
        let mut functions = Self::default();
        for definition in definitions {
            if let Some(Sbml::Lambda { params, body }) = &definition.math {
                functions
                    .definitions
                    .insert(definition.id.clone(), (params.clone(), (**body).clone()));
            } else {
                functions.without_lambda.insert(definition.id.clone());
            }
        }
        functions.recursive = functions.cycles();
        functions
    }

    /// The ids of the definitions which are part of a cycle of calls.
    fn cycles(&self) -> HashSet<String> {
        let mut recursive = HashSet::new();
        for id in self.definitions.keys() {
            let mut seen = HashSet::new();
            if self.reaches(id, id, &mut seen) {
                recursive.insert(id.clone());
            }
        }
        recursive
    }

    /// Whether `from` calls `target`, over any number of definitions.
    fn reaches(&self, from: &str, target: &str, seen: &mut HashSet<String>) -> bool {
        if !seen.insert(from.to_string()) {
            return false;
        }
        let Some((_, body)) = self.definitions.get(from) else {
            return false;
        };
        for called in calls(body) {
            if called == target || self.reaches(called, target, seen) {
                return true;
            }
        }
        false
    }

    /// A formula with every call of a function definition replaced by its
    /// body, the arguments in the place of the parameters.
    ///
    /// The arguments are expanded before they are substituted, and the body
    /// again after, so a call inside an argument and a call inside a body
    /// are expanded as well.
    pub fn expand(&self, node: &Sbml) -> Result<Sbml, MathError> {
        match node {
            Sbml::Apply {
                op: Op::Function(name),
                args,
            } => {
                let arguments = args
                    .iter()
                    .map(|argument| self.expand(argument))
                    .collect::<Result<Vec<_>, _>>()?;
                if self.recursive.contains(name) {
                    return Err(MathError::Recursive(name.clone()));
                }
                let Some((parameters, body)) = self.definitions.get(name) else {
                    return Err(if self.without_lambda.contains(name) {
                        MathError::NoLambda(name.clone())
                    } else {
                        MathError::Unknown(name.clone())
                    });
                };
                if parameters.len() != arguments.len() {
                    return Err(MathError::Arguments {
                        name: name.clone(),
                        parameters: parameters.len(),
                        arguments: arguments.len(),
                    });
                }
                let values: HashMap<&str, &Sbml> = parameters
                    .iter()
                    .map(String::as_str)
                    .zip(arguments.iter())
                    .collect();
                self.expand(&substitute(body, &values))
            }
            Sbml::Apply { op, args } => Ok(Sbml::Apply {
                op: op.clone(),
                args: args
                    .iter()
                    .map(|argument| self.expand(argument))
                    .collect::<Result<Vec<_>, _>>()?,
            }),
            Sbml::Piecewise { pieces, otherwise } => Ok(Sbml::Piecewise {
                pieces: pieces
                    .iter()
                    .map(|(value, condition)| Ok((self.expand(value)?, self.expand(condition)?)))
                    .collect::<Result<Vec<_>, MathError>>()?,
                otherwise: match otherwise {
                    Some(otherwise) => Some(Box::new(self.expand(otherwise)?)),
                    None => None,
                },
            }),
            Sbml::Lambda { params, body } => Ok(Sbml::Lambda {
                params: params.clone(),
                body: Box::new(self.expand(body)?),
            }),
            other => Ok(other.clone()),
        }
    }
}

/// The ids of the function definitions a formula calls.
fn calls(node: &Sbml) -> Vec<&str> {
    let mut called = Vec::new();
    collect_calls(node, &mut called);
    called
}

/// Collects the ids of the called function definitions, in order.
fn collect_calls<'a>(node: &'a Sbml, called: &mut Vec<&'a str>) {
    match node {
        Sbml::Apply { op, args } => {
            if let Op::Function(name) = op {
                called.push(name.as_str());
            }
            for argument in args {
                collect_calls(argument, called);
            }
        }
        Sbml::Piecewise { pieces, otherwise } => {
            for (value, condition) in pieces {
                collect_calls(value, called);
                collect_calls(condition, called);
            }
            if let Some(otherwise) = otherwise {
                collect_calls(otherwise, called);
            }
        }
        Sbml::Lambda { body, .. } => collect_calls(body, called),
        _ => {}
    }
}

/// A formula with the symbols of `values` replaced by their expressions.
fn substitute(node: &Sbml, values: &HashMap<&str, &Sbml>) -> Sbml {
    match node {
        Sbml::Symbol(name) => values
            .get(name.as_str())
            .map_or_else(|| node.clone(), |value| (*value).clone()),
        Sbml::Apply { op, args } => Sbml::Apply {
            op: op.clone(),
            args: args
                .iter()
                .map(|argument| substitute(argument, values))
                .collect(),
        },
        Sbml::Piecewise { pieces, otherwise } => Sbml::Piecewise {
            pieces: pieces
                .iter()
                .map(|(value, condition)| {
                    (substitute(value, values), substitute(condition, values))
                })
                .collect(),
            otherwise: otherwise
                .as_ref()
                .map(|otherwise| Box::new(substitute(otherwise, values))),
        },
        Sbml::Lambda { params, body } => Sbml::Lambda {
            params: params.clone(),
            body: Box::new(substitute(body, values)),
        },
        other => other.clone(),
    }
}

/// What the names of a formula stand for in the CellML model.
pub struct Names<'a> {
    /// The name of the variable an SBML id stands for, which is the id
    /// itself for most of them; a local parameter of a kinetic law and a
    /// species in an amount are named differently.
    pub variable: &'a dyn Fn(&str) -> String,
    /// The name of the variable of integration, which the time symbol of
    /// SBML becomes.
    pub time: &'a str,
}

impl Names<'_> {
    /// The name of a variable.
    fn of(&self, id: &str) -> String {
        (self.variable)(id)
    }
}

/// The formula as the mathematics of CellML.
///
/// The units of the numbers are taken from `units`, which adds the units of
/// a number to the model when it has to, so the model defines everything its
/// mathematics references.
pub fn expression(node: &Sbml, names: &Names, units: &mut Units) -> Result<Node, MathError> {
    match node {
        Sbml::Number { value, units: of } => Ok(number(*value, of.as_deref(), units)),
        Sbml::Symbol(name) => Ok(Node::Identifier(names.of(name))),
        Sbml::CsymbolTime => Ok(Node::Identifier(names.time.to_string())),
        Sbml::CsymbolAvogadro => Ok(Node::Number {
            value: AVOGADRO_VALUE,
            units: Some(DIMENSIONLESS.to_string()),
        }),
        Sbml::CsymbolDelay => Err(MathError::Delay),
        Sbml::CsymbolRateOf => Err(MathError::RateOf),
        Sbml::Apply { op, args } => apply(op, args, names, units),
        Sbml::Piecewise { pieces, otherwise } => Ok(Node::Piecewise {
            pieces: pieces
                .iter()
                .map(|(value, condition)| {
                    Ok((
                        expression(value, names, units)?,
                        expression(condition, names, units)?,
                    ))
                })
                .collect::<Result<Vec<_>, MathError>>()?,
            otherwise: match otherwise {
                Some(otherwise) => Some(Box::new(expression(otherwise, names, units)?)),
                None => None,
            },
        }),
        Sbml::Lambda { .. } => Err(MathError::Lambda),
        Sbml::True => Ok(Node::Constant(Constant::True)),
        Sbml::False => Ok(Node::Constant(Constant::False)),
        Sbml::Pi => Ok(Node::Constant(Constant::Pi)),
        Sbml::ExponentialE => Ok(Node::Constant(Constant::Exponentiale)),
        Sbml::Infinity => Ok(Node::Constant(Constant::Infinity)),
        Sbml::NotANumber => Ok(Node::Constant(Constant::NotANumber)),
        Sbml::Empty => Err(MathError::Empty),
    }
}

/// A number with the CellML name of its units, `dimensionless` when it
/// carries none; an infinity and a NaN are the elements of MathML, which
/// carry no units.
fn number(value: f64, of: Option<&str>, units: &mut Units) -> Node {
    if value.is_nan() {
        return Node::Constant(Constant::NotANumber);
    }
    if value.is_infinite() {
        let infinity = Node::Constant(Constant::Infinity);
        return if value.is_sign_negative() {
            Node::Apply {
                operator: Operator::Other("minus".to_string()),
                arguments: vec![infinity],
            }
        } else {
            infinity
        };
    }
    Node::Number {
        value,
        units: Some(match of {
            Some(reference) => units.number_units(reference),
            None => DIMENSIONLESS.to_string(),
        }),
    }
}

/// A dimensionless number, the value of an operator without arguments.
fn dimensionless(value: f64) -> Node {
    Node::Number {
        value,
        units: Some(DIMENSIONLESS.to_string()),
    }
}

/// An operator applied to its arguments.
fn apply(op: &Op, args: &[Sbml], names: &Names, units: &mut Units) -> Result<Node, MathError> {
    match op {
        Op::Delay => return Err(MathError::Delay),
        Op::RateOf => return Err(MathError::RateOf),
        Op::Function(name) => return Err(MathError::Unknown(name.clone())),
        _ => {}
    }
    // a sum of sums and a product of products are written as one operator
    // of all of their arguments, as libsbml writes them, so that both
    // converters give an equation the same mathematics
    let spliced = matches!(op, Op::Plus | Op::Times).then(|| splice(op, args));
    let args = spliced.as_deref().unwrap_or(args);
    // the value of an n-ary operator of less than two arguments
    if let Some(empty) = identity(op)
        && args.len() < 2
    {
        return match args.first() {
            Some(only) => expression(only, names, units),
            None => Ok(empty),
        };
    }
    let mut arguments = args
        .iter()
        .map(|argument| expression(argument, names, units))
        .collect::<Result<Vec<_>, MathError>>()?;
    // a relation of more than two arguments is the conjunction of its pairs
    if is_relation(op) && arguments.len() > 2 {
        let pairs = arguments
            .windows(2)
            .map(|pair| Node::Apply {
                operator: Operator::Other(operator(op).to_string()),
                arguments: pair.to_vec(),
            })
            .collect();
        return Ok(Node::Apply {
            operator: Operator::Other("and".to_string()),
            arguments: pairs,
        });
    }
    match op {
        // CellML has no quotient: it is the floor of the division
        Op::Quotient if arguments.len() == 2 => Ok(Node::Apply {
            operator: Operator::Other("floor".to_string()),
            arguments: vec![Node::Apply {
                operator: Operator::Other("divide".to_string()),
                arguments,
            }],
        }),
        // CellML has no implies: `a implies b` is `not a or b`
        Op::Implies if arguments.len() == 2 => {
            let consequence = arguments.pop().unwrap_or_else(|| dimensionless(0.0));
            let condition = arguments.pop().unwrap_or_else(|| dimensionless(0.0));
            Ok(Node::Apply {
                operator: Operator::Other("or".to_string()),
                arguments: vec![
                    Node::Apply {
                        operator: Operator::Other("not".to_string()),
                        arguments: vec![condition],
                    },
                    consequence,
                ],
            })
        }
        // the degree of a root and the base of a logarithm are qualifiers,
        // which keep their place among the arguments
        Op::Root if arguments.len() == 2 => Ok(qualified("root", "degree", arguments)),
        Op::Log if arguments.len() == 2 => Ok(qualified("log", "logbase", arguments)),
        _ => Ok(Node::Apply {
            operator: Operator::Other(operator(op).to_string()),
            arguments,
        }),
    }
}

/// The arguments of an operator with the arguments of its nested uses of
/// the same operator in their place, `plus(plus(a, b), c)` as
/// `plus(a, b, c)`.
///
/// A nested use of less than two arguments keeps its place, since it stands
/// for its value, which is a term of the sum: `plus(1, plus())` is
/// `plus(1, 0)` and not `plus(1)`.
fn splice(op: &Op, args: &[Sbml]) -> Vec<Sbml> {
    let mut spliced = Vec::with_capacity(args.len());
    for argument in args {
        match argument {
            Sbml::Apply { op: nested, args } if nested == op && args.len() > 1 => {
                spliced.extend(splice(op, args));
            }
            other => spliced.push(other.clone()),
        }
    }
    spliced
}

/// An operator whose first argument is a qualifier, `root` and `log`.
fn qualified(name: &str, qualifier: &str, mut arguments: Vec<Node>) -> Node {
    let expression = arguments.pop().unwrap_or_else(|| dimensionless(0.0));
    let value = arguments.pop().unwrap_or_else(|| dimensionless(0.0));
    Node::Apply {
        operator: Operator::Other(name.to_string()),
        arguments: vec![
            Node::Qualifier {
                name: qualifier.to_string(),
                value: Box::new(value),
            },
            expression,
        ],
    }
}

/// The value of an n-ary operator without arguments, the identity element
/// MathML gives it, for the operators which have one.
fn identity(op: &Op) -> Option<Node> {
    match op {
        Op::Plus => Some(dimensionless(0.0)),
        Op::Times => Some(dimensionless(1.0)),
        Op::And => Some(Node::Constant(Constant::True)),
        Op::Or | Op::Xor => Some(Node::Constant(Constant::False)),
        _ => None,
    }
}

/// Whether the operator is a relation, which MathML allows with more than
/// two arguments and CellML with two.
fn is_relation(op: &Op) -> bool {
    matches!(op, Op::Eq | Op::Neq | Op::Gt | Op::Lt | Op::Geq | Op::Leq)
}

/// The name of the MathML element of an operator, which CellML and SBML
/// share.
fn operator(op: &Op) -> &'static str {
    match op {
        Op::Plus => "plus",
        Op::Minus => "minus",
        Op::Times => "times",
        Op::Divide => "divide",
        Op::Power => "power",
        Op::Root => "root",
        Op::Abs => "abs",
        Op::Exp => "exp",
        Op::Ln => "ln",
        Op::Log => "log",
        Op::Floor => "floor",
        Op::Ceiling => "ceiling",
        Op::Factorial => "factorial",
        Op::Sin => "sin",
        Op::Cos => "cos",
        Op::Tan => "tan",
        Op::Sec => "sec",
        Op::Csc => "csc",
        Op::Cot => "cot",
        Op::Sinh => "sinh",
        Op::Cosh => "cosh",
        Op::Tanh => "tanh",
        Op::Sech => "sech",
        Op::Csch => "csch",
        Op::Coth => "coth",
        Op::Arcsin => "arcsin",
        Op::Arccos => "arccos",
        Op::Arctan => "arctan",
        Op::Arcsec => "arcsec",
        Op::Arccsc => "arccsc",
        Op::Arccot => "arccot",
        Op::Arcsinh => "arcsinh",
        Op::Arccosh => "arccosh",
        Op::Arctanh => "arctanh",
        Op::Arcsech => "arcsech",
        Op::Arccsch => "arccsch",
        Op::Arccoth => "arccoth",
        Op::Eq => "eq",
        Op::Neq => "neq",
        Op::Gt => "gt",
        Op::Lt => "lt",
        Op::Geq => "geq",
        Op::Leq => "leq",
        Op::And => "and",
        Op::Or => "or",
        Op::Xor => "xor",
        Op::Not => "not",
        Op::Max => "max",
        Op::Min => "min",
        Op::Rem => "rem",
        // replaced before, the operators CellML does not have and the ones
        // which are no expression of it
        Op::Quotient => "quotient",
        Op::Implies => "implies",
        Op::Delay => "delay",
        Op::RateOf => "rateOf",
        Op::Function(_) => "function",
    }
}
