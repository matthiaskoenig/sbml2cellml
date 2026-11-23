//! The MathML of a CellML component: content MathML as a tree of [`Node`]s.
//!
//! CellML uses a subset of content MathML, with one addition: every number
//! carries the units it is in (`cellml:units`), which SBML writes as
//! `sbml:units`. [`equations`] reads the children of a `<math>` element,
//! every one of them an equation of the component.
//!
//! Nothing here is interpreted: an operator the reader does not know is
//! [`Operator::Other`] and an element it does not know is [`Node::Other`],
//! so a document is read as it is written and the converter decides what
//! it can handle.

use roxmltree::Node as X;
use thiserror::Error;

/// The namespace of content MathML.
pub const MATHML_NS: &str = "http://www.w3.org/1998/Math/MathML";

/// A failure to read the mathematics of a component.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum MathError {
    /// An `<apply>` without an operator.
    #[error("an apply element has no operator")]
    EmptyApply,
    /// A `<ci>` without a name.
    #[error("a ci element has no variable name")]
    EmptyIdentifier,
    /// A `<cn>` whose text is no number.
    #[error("'{0}' is not a number")]
    NotANumber(String),
    /// A `<piece>` without its value and its condition.
    #[error("a piece element needs a value and a condition, it has {0}")]
    BadPiece(usize),
    /// A `<bvar>` of a derivative without a variable.
    #[error("a derivative has no variable of integration")]
    BadDerivative,
}

/// A constant of MathML.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Constant {
    /// `<pi/>`.
    Pi,
    /// `<exponentiale/>`.
    Exponentiale,
    /// `<true/>`.
    True,
    /// `<false/>`.
    False,
    /// `<infinity/>`.
    Infinity,
    /// `<notanumber/>`.
    NotANumber,
}

impl Constant {
    /// The constant of an element name, `None` for any other name.
    pub fn from_name(name: &str) -> Option<Self> {
        Some(match name {
            "pi" => Self::Pi,
            "exponentiale" => Self::Exponentiale,
            "true" => Self::True,
            "false" => Self::False,
            "infinity" => Self::Infinity,
            "notanumber" => Self::NotANumber,
            _ => return None,
        })
    }
}

/// The operator of an `<apply>`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Operator {
    /// `<eq/>`, the equals of an equation.
    Eq,
    /// Any other operator, by the name of its element, e.g. `plus`,
    /// `times`, `sin` or `leq`: the reader keeps the name and the
    /// converter decides what it writes for it.
    Other(String),
}

impl Operator {
    /// The operator of an element name.
    pub fn from_name(name: &str) -> Self {
        if name == "eq" {
            Self::Eq
        } else {
            Self::Other(name.to_string())
        }
    }

    /// The name of the element of the operator.
    pub fn name(&self) -> &str {
        match self {
            Self::Eq => "eq",
            Self::Other(name) => name,
        }
    }
}

/// A node of the mathematics of a component.
#[derive(Debug, Clone, PartialEq)]
pub enum Node {
    /// A number with the units it is in (`cellml:units`), which a document
    /// of CellML 2.0 requires and one of CellML 1.0 and 1.1 may leave out.
    Number {
        /// The value of the text of the element.
        value: f64,
        /// The units of the number, the attribute `cellml:units`.
        units: Option<String>,
    },
    /// A variable, `<ci>`.
    Identifier(String),
    /// A constant of MathML.
    Constant(Constant),
    /// An operator applied to its arguments, `<apply>`.
    Apply {
        /// The operator.
        operator: Operator,
        /// The arguments, in the order of the document.
        arguments: Vec<Node>,
    },
    /// `<piecewise>`: the pieces and the value of none of them.
    Piecewise {
        /// The value and the condition of every `<piece>`.
        pieces: Vec<(Node, Node)>,
        /// The `<otherwise>`, absent when the element has none.
        otherwise: Option<Box<Node>>,
    },
    /// A derivative, `<apply><diff/><bvar>...`.
    Derivative {
        /// The variable of integration, the `<ci>` of the `<bvar>`.
        variable: String,
        /// The degree of the `<bvar>`, 1 without one.
        degree: u32,
        /// What is differentiated.
        expression: Box<Node>,
    },
    /// A qualifier of an operator: the `<degree>` of a root and the
    /// `<logbase>` of a logarithm, which keep their place among the
    /// arguments of the `<apply>`.
    Qualifier {
        /// The name of the element, `degree` or `logbase`.
        name: String,
        /// Its expression.
        value: Box<Node>,
    },
    /// An element the reader does not model, by its name.
    Other(String),
}

/// The equations of a `<math>` element.
///
/// # Arguments
///
/// * `math` - a `<math>` element of a component.
/// * `cellml_ns` - the namespace of the CellML version of the document,
///   which holds the `units` attribute of a number.
///
/// # Errors
///
/// Returns the first [`MathError`] of the children of the element.
pub fn equations(math: X, cellml_ns: &str) -> Result<Vec<Node>, MathError> {
    math.children()
        .filter(|child| child.is_element())
        .map(|child| parse(child, cellml_ns))
        .collect()
}

/// One node of MathML.
///
/// # Arguments
///
/// * `node` - an element of content MathML.
/// * `cellml_ns` - the namespace of the CellML version of the document.
///
/// # Errors
///
/// Returns a [`MathError`] when an element is written in a way the reader
/// cannot make a node of, e.g. an `<apply>` without an operator.
pub fn parse(node: X, cellml_ns: &str) -> Result<Node, MathError> {
    let name = node.tag_name().name();
    if let Some(constant) = Constant::from_name(name) {
        return Ok(Node::Constant(constant));
    }
    match name {
        "cn" => number(node, cellml_ns),
        "ci" => {
            let text = text_of(node);
            if text.is_empty() {
                Err(MathError::EmptyIdentifier)
            } else {
                Ok(Node::Identifier(text))
            }
        }
        "apply" => apply(node, cellml_ns),
        // the qualifiers of a root and of a logarithm, which SBML writes
        // the same way; the `<bvar>` of a derivative is read with it
        "degree" | "logbase" => match elements(node).first() {
            Some(value) => Ok(Node::Qualifier {
                name: name.to_string(),
                value: Box::new(parse(*value, cellml_ns)?),
            }),
            None => Ok(Node::Other(name.to_string())),
        },
        "piecewise" => piecewise(node, cellml_ns),
        // a `<math>` or a `<semantics>` around an expression
        "math" | "semantics" => {
            let mut children = elements(node);
            match children.len() {
                1 => parse(children.remove(0), cellml_ns),
                _ => Ok(Node::Other(name.to_string())),
            }
        }
        _ => Ok(Node::Other(name.to_string())),
    }
}

/// The elements of a node, in the order of the document.
fn elements<'a>(node: X<'a, 'a>) -> Vec<X<'a, 'a>> {
    node.children().filter(|child| child.is_element()).collect()
}

/// The text of an element with the whitespace around it removed.
fn text_of(node: X) -> String {
    node.text().unwrap_or_default().trim().to_string()
}

/// A `<cn>`, its value and its units.
fn number(node: X, cellml_ns: &str) -> Result<Node, MathError> {
    let units = node
        .attribute((cellml_ns, "units"))
        .or_else(|| node.attribute("units"))
        .map(str::to_string);
    let text = text_of(node);
    // `<cn type="e-notation">1<sep/>3</cn>` is 1e3, the notation of MathML
    let value =
        if let Some(separator) = elements(node).iter().find(|e| e.tag_name().name() == "sep") {
            let mantissa = separator
                .prev_sibling()
                .and_then(|previous| previous.text())
                .unwrap_or_default()
                .trim()
                .to_string();
            let exponent = separator
                .next_sibling()
                .and_then(|next| next.text())
                .unwrap_or_default()
                .trim()
                .to_string();
            format!("{mantissa}e{exponent}")
                .parse::<f64>()
                .map_err(|_| MathError::NotANumber(format!("{mantissa}e{exponent}")))?
        } else {
            text.parse::<f64>()
                .map_err(|_| MathError::NotANumber(text.clone()))?
        };
    Ok(Node::Number { value, units })
}

/// An `<apply>`, a derivative when its operator is `<diff/>`.
fn apply(node: X, cellml_ns: &str) -> Result<Node, MathError> {
    let children = elements(node);
    let (operator, arguments) = children.split_first().ok_or(MathError::EmptyApply)?;
    if operator.tag_name().name() == "diff" {
        return derivative(arguments, cellml_ns);
    }
    Ok(Node::Apply {
        operator: Operator::from_name(operator.tag_name().name()),
        arguments: arguments
            .iter()
            .map(|argument| parse(*argument, cellml_ns))
            .collect::<Result<Vec<_>, _>>()?,
    })
}

/// The `<bvar>` and the expression of a derivative.
fn derivative(arguments: &[X], cellml_ns: &str) -> Result<Node, MathError> {
    let bvar = arguments
        .iter()
        .find(|argument| argument.tag_name().name() == "bvar")
        .ok_or(MathError::BadDerivative)?;
    let variable = elements(*bvar)
        .into_iter()
        .find(|child| child.tag_name().name() == "ci")
        .map(text_of)
        .ok_or(MathError::BadDerivative)?;
    let degree_element = elements(*bvar)
        .into_iter()
        .find(|child| child.tag_name().name() == "degree")
        .or_else(|| {
            arguments
                .iter()
                .copied()
                .find(|argument| argument.tag_name().name() == "degree")
        });
    let degree = degree_element
        .and_then(|child| {
            elements(child)
                .first()
                .map(|number| text_of(*number))
                .or_else(|| Some(text_of(child)))
        })
        .and_then(|text| text.trim().parse::<f64>().ok())
        .map(|value| value as u32)
        .unwrap_or(1);
    let expression = arguments
        .iter()
        .find(|argument| !matches!(argument.tag_name().name(), "bvar" | "degree"))
        .ok_or(MathError::BadDerivative)?;
    Ok(Node::Derivative {
        variable,
        degree,
        expression: Box::new(parse(*expression, cellml_ns)?),
    })
}

/// A `<piecewise>` with its pieces and its otherwise.
fn piecewise(node: X, cellml_ns: &str) -> Result<Node, MathError> {
    let mut pieces = Vec::new();
    let mut otherwise = None;
    for child in elements(node) {
        match child.tag_name().name() {
            "piece" => {
                let parts = elements(child);
                if parts.len() != 2 {
                    return Err(MathError::BadPiece(parts.len()));
                }
                pieces.push((parse(parts[0], cellml_ns)?, parse(parts[1], cellml_ns)?));
            }
            "otherwise" => {
                if let Some(value) = elements(child).first() {
                    otherwise = Some(Box::new(parse(*value, cellml_ns)?));
                }
            }
            _ => {}
        }
    }
    Ok(Node::Piecewise { pieces, otherwise })
}
