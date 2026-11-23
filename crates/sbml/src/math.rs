//! The mathematics of an SBML document: the MathML subset of SBML.

/// A constant of MathML which SBML level 3 version 2 allows.
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
    /// The name of the element of the constant.
    pub fn name(self) -> &'static str {
        match self {
            Self::Pi => "pi",
            Self::Exponentiale => "exponentiale",
            Self::True => "true",
            Self::False => "false",
            Self::Infinity => "infinity",
            Self::NotANumber => "notanumber",
        }
    }
}

/// An expression of an SBML document.
#[derive(Debug, Clone, PartialEq)]
pub enum Math {
    /// A number with the id of its units, which SBML writes as
    /// `sbml:units` and which every number of a CellML model has.
    Number {
        /// The value.
        value: f64,
        /// The id of the units, left out when the model has none.
        units: Option<String>,
    },
    /// A parameter, by its SBML id.
    Identifier(String),
    /// Time, the `csymbol` of SBML, which the variable of integration of
    /// the CellML model becomes.
    Time,
    /// A constant.
    Constant(Constant),
    /// An operator applied to its arguments, by the name of its MathML
    /// element (`plus`, `times`, `leq`, `sin`, ...).
    Apply {
        /// The name of the element of the operator.
        operator: String,
        /// The arguments, in order.
        arguments: Vec<Math>,
    },
    /// The rate of change of a parameter, the `csymbol` `rateOf` of SBML
    /// level 3 version 2, which a derivative inside an expression becomes.
    RateOf(String),
    /// A qualifier of an operator, the `<degree>` of a root or the
    /// `<logbase>` of a logarithm, in its place among the arguments.
    Qualifier {
        /// The name of the element, `degree` or `logbase`.
        name: String,
        /// Its expression.
        value: Box<Math>,
    },
    /// `<piecewise>`: the value and the condition of every piece, and the
    /// value of none of them.
    Piecewise {
        /// The pieces, value and condition.
        pieces: Vec<(Math, Math)>,
        /// The `<otherwise>`, absent when there is none.
        otherwise: Option<Box<Math>>,
    },
}

impl Math {
    /// A number with its units.
    pub fn number(value: f64, units: Option<&str>) -> Self {
        Self::Number {
            value,
            units: units.map(str::to_string),
        }
    }

    /// A parameter by its id.
    pub fn identifier(id: &str) -> Self {
        Self::Identifier(id.to_string())
    }

    /// An operator applied to its arguments.
    pub fn apply(operator: &str, arguments: Vec<Self>) -> Self {
        Self::Apply {
            operator: operator.to_string(),
            arguments,
        }
    }
}
