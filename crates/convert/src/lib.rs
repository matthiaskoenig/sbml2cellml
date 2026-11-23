//! Conversion of a CellML model to an SBML level 3 version 2 model.
//!
//! Every equivalence set of variables becomes one parameter, every
//! equation a rule: the rate of a state a rate rule, an equation which
//! determines one variable an assignment rule, one which computes a
//! constant an initial assignment and an implicit equation an algebraic
//! rule. The custom units of the model become unit definitions whose units
//! are the base units of SBML, and the mathematics keeps its operators,
//! with the variable of integration written as the time of SBML.
//!
//! The crate reads nothing from the file system and resolves no import, so
//! it builds for the web: a model whose components are imported is refused
//! until the import is resolved.
//!
//! ```
//! let document = cellml::read(
//!     r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="decay">
//!          <units name="mole_per_second">
//!            <unit units="mole"/>
//!            <unit units="second" exponent="-1"/>
//!          </units>
//!          <component name="c">
//!            <variable name="t" units="second" interface="none"/>
//!            <variable name="x" units="mole" initial_value="10"/>
//!            <math xmlns="http://www.w3.org/1998/Math/MathML">
//!              <apply><eq/>
//!                <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
//!                <cn cellml:units="mole_per_second"
//!                    xmlns:cellml="http://www.cellml.org/cellml/2.0#">-1</cn>
//!              </apply>
//!            </math>
//!          </component>
//!        </model>"#,
//! )
//! .unwrap();
//! let xml = convert::convert(&document.model).unwrap().document.to_xml();
//! assert!(xml.contains("<rateRule variable=\"x\">"));
//! assert!(xml.contains("timeUnits=\"second\""));
//! ```

pub mod analysis;
pub mod ids;
pub mod math;
pub mod units;

use analysis::{Analysis, AnalysisError, EquationKind, analyse};
use cellml::{Model, Node};
use ids::Ids;
use math::{Context, MathError, equality, expression};
use sbml::{Document, InitialAssignment, Math, Parameter, Rule};
use thiserror::Error;
use units::{UnitsError, unit_definitions};

/// A failure to convert a model.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum ConvertError {
    /// The units of the model cannot be converted.
    #[error(transparent)]
    Units(#[from] UnitsError),
    /// The equations of the model cannot be read.
    #[error(transparent)]
    Analysis(#[from] AnalysisError),
    /// An expression has no counterpart in SBML.
    #[error(transparent)]
    Math(#[from] MathError),
    /// An initial value which is neither a number nor a variable of the
    /// component of the variable it initialises.
    #[error(
        "initial value '{value}' of variable '{variable}' is no number and no variable of component '{component}'"
    )]
    InitialValue {
        /// The initial value as it is written.
        value: String,
        /// The name of the variable it initialises.
        variable: String,
        /// The name of the component of that variable.
        component: String,
    },
}

/// The SBML document of a CellML model and what the conversion found.
#[derive(Debug, Clone)]
pub struct Conversion {
    /// The document.
    pub document: Document,
    /// What the conversion is told about, e.g. a variable without a value.
    pub warnings: Vec<String>,
}

/// Convert a CellML model to an SBML level 3 version 2 document.
///
/// # Arguments
///
/// * `model` - the model, with its imports resolved.
///
/// # Errors
///
/// Returns the first [`ConvertError`] of the model.
pub fn convert(model: &Model) -> Result<Conversion, ConvertError> {
    let mut ids = Ids::new(model);
    let (unit_definitions, unit_ids, mut warnings) = unit_definitions(model)?;
    let analysis = analyse(model, &ids)?;
    let name = if model.name.is_empty() {
        "model".to_string()
    } else {
        model.name.clone()
    };
    let model_id = ids.reserve(&name);
    let context = Context {
        model,
        ids: &ids,
        units: &unit_ids,
        voi: analysis.voi,
    };

    warnings.extend(analysis.warnings.iter().cloned());
    let mut parameters = Vec::new();
    let mut initial_assignments = Vec::new();
    for quantity in 0..ids.len() {
        if Some(quantity) == analysis.voi {
            continue;
        }
        let reference = ids.set(quantity)[0];
        let variable = &model.components[reference.component].variables[reference.variable];
        let id = ids.id(quantity).to_string();
        let mut value = None;
        if !analysis.computed.contains(&quantity) {
            if let Some((initial, member)) = initial_value(model, &ids, quantity) {
                match initial.parse::<f64>() {
                    Ok(number) => value = Some(number),
                    Err(_) => {
                        // CellML 2.0 initialises a variable with another
                        // variable of its component
                        let referenced =
                            ids.quantity_of(model, member, &initial).ok_or_else(|| {
                                ConvertError::InitialValue {
                                    value: initial.clone(),
                                    variable: variable.name.clone(),
                                    component: model.components[member].name.clone(),
                                }
                            })?;
                        initial_assignments.push(InitialAssignment {
                            symbol: id.clone(),
                            math: Math::Identifier(ids.id(referenced).to_string()),
                        });
                    }
                }
            } else if !analysis.states.contains(&quantity)
                && analysis::equation_of(&analysis, quantity).is_none()
                && !analysis.implicit.contains(&quantity)
            {
                warnings.push(format!(
                    "variable '{id}' has neither a value nor an equation"
                ));
            }
        }
        let units = unit_ids
            .resolve(&variable.units)
            .ok_or_else(|| MathError::Units(variable.units.clone()))?;
        parameters.push(Parameter {
            name: (id != variable.name).then(|| variable.name.clone()),
            id,
            value,
            units: Some(units),
            constant: analysis.is_constant(quantity),
        });
    }

    let mut rules = Vec::new();
    for equation in &analysis.equations {
        let node = &model.components[equation.component].math[equation.index];
        let Some((left, right)) = equality(node) else {
            continue;
        };
        match equation.kind {
            EquationKind::Rate { state } => {
                let side = other_side(left, right, |node| matches!(node, Node::Derivative { .. }));
                rules.push(Rule::Rate {
                    variable: ids.id(state).to_string(),
                    math: expression(side, equation.component, context)?,
                });
            }
            EquationKind::Assignment { target } => {
                let id = ids.id(target);
                let side = other_side(left, right, |node| {
                    matches!(node, Node::Identifier(name)
                        if context.ids.quantity_of(model, equation.component, name) == Some(target))
                });
                let math = expression(side, equation.component, context)?;
                if analysis.computed.contains(&target) {
                    initial_assignments.push(InitialAssignment {
                        symbol: id.to_string(),
                        math,
                    });
                } else {
                    rules.push(Rule::Assignment {
                        variable: id.to_string(),
                        math,
                    });
                }
            }
            EquationKind::Algebraic => {
                // `left = right` is the residual `left - right`, which
                // SBML sets to zero
                rules.push(Rule::Algebraic {
                    math: Math::apply(
                        "minus",
                        vec![
                            expression(left, equation.component, context)?,
                            expression(right, equation.component, context)?,
                        ],
                    ),
                });
            }
        }
    }

    let time_units = match analysis.voi {
        Some(voi) => {
            let reference = ids.set(voi)[0];
            let units = &model.components[reference.component].variables[reference.variable].units;
            Some(
                unit_ids
                    .resolve(units)
                    .ok_or_else(|| MathError::Units(units.clone()))?,
            )
        }
        None => None,
    };

    Ok(Conversion {
        document: Document {
            model: sbml::Model {
                id: Some(model_id),
                name: Some(name),
                time_units,
                unit_definitions,
                parameters,
                initial_assignments,
                rules,
            },
        },
        warnings,
    })
}

/// The side of an equation which is not the one the test matches.
fn other_side<'a>(left: &'a Node, right: &'a Node, matches: impl Fn(&Node) -> bool) -> &'a Node {
    if matches(left) { right } else { left }
}

/// The initial value of a quantity and the component it is written in: the
/// first member of the equivalence set which has one.
fn initial_value(model: &Model, ids: &Ids, quantity: usize) -> Option<(String, usize)> {
    ids.set(quantity).iter().find_map(|member| {
        model.components[member.component].variables[member.variable]
            .initial_value
            .clone()
            .map(|value| (value, member.component))
    })
}

/// What the analysis of a model found, for a caller which wants it without
/// the document, e.g. a report over a corpus.
pub fn analysis(model: &Model) -> Result<(Ids, Analysis), ConvertError> {
    let ids = Ids::new(model);
    let analysis = analyse(model, &ids)?;
    Ok((ids, analysis))
}
