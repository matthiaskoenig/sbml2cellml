//! What the equations of a CellML model determine.
//!
//! libcellml hands the python converter an analysed model, which types
//! every variable and every equation. The rust converter reads the
//! equations itself: a derivative on one side of an equation makes the
//! other side the rate of a state, an equation with a single variable on
//! one side determines that variable, and an equation which determines no
//! single variable is implicit. A variable which no equation determines
//! keeps the value it is initialised with.

use crate::ids::Ids;
use crate::math::{MathError, equality, rate_variables as math_rates, variables};
use cellml::{Model, Node};
use std::collections::{BTreeSet, HashMap, HashSet};
use thiserror::Error;

/// A failure to read the equations of a model.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum AnalysisError {
    /// A component whose import is not resolved, which has neither
    /// variables nor equations.
    #[error("component '{0}' is imported, which the converter does not resolve")]
    Imported(String),
    /// Units of the model which are imported, so that the definition of
    /// the units of a variable is not known.
    #[error("units '{0}' are imported, which the converter does not resolve")]
    ImportedUnits(String),
    /// Rate equations which give the rate of a state through the rate of
    /// another, so that neither can be written as a rate rule.
    #[error("the rate of '{first}' and the rate of '{second}' are given by each other")]
    ImplicitRates {
        /// The id of the first state.
        first: String,
        /// The id of the second one.
        second: String,
    },
    /// Derivatives with respect to two different variables.
    #[error("the model is differentiated with respect to '{first}' and to '{second}'")]
    SeveralVoi {
        /// The name of the first variable of integration.
        first: String,
        /// The name of the second one.
        second: String,
    },
    /// Two equations for the rate of the same variable.
    #[error("the rate of '{0}' is given by two equations")]
    TwoRates(String),
    /// A derivative of an order SBML cannot express, or of an expression.
    #[error("a derivative of the order {0} has no counterpart in SBML")]
    HigherOrder(u32),
    /// A variable of an equation which its component does not have.
    #[error(transparent)]
    Math(#[from] MathError),
}

/// What an equation of the model determines.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EquationKind {
    /// The rate of change of a state.
    Rate {
        /// The quantity the equation integrates.
        state: usize,
    },
    /// The value of one quantity.
    Assignment {
        /// The quantity the equation determines.
        target: usize,
    },
    /// No single quantity: the equation is implicit.
    Algebraic,
}

/// One equation of the model.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Equation {
    /// The index of the component the equation is in.
    pub component: usize,
    /// The index of the equation in the mathematics of the component.
    pub index: usize,
    /// What it determines.
    pub kind: EquationKind,
}

/// What the equations of a model determine.
#[derive(Debug, Clone, Default)]
pub struct Analysis {
    /// The quantity of the variable of integration, `None` for a model
    /// without a derivative.
    pub voi: Option<usize>,
    /// The equations of the model, in the order of its components.
    pub equations: Vec<Equation>,
    /// The quantities a rate equation integrates.
    pub states: BTreeSet<usize>,
    /// The quantities whose value never changes: those which no equation
    /// determines and those an equation computes from such quantities.
    pub constants: BTreeSet<usize>,
    /// The quantities an equation computes from constants, which become an
    /// initial assignment.
    pub computed: BTreeSet<usize>,
    /// The quantities an implicit equation determines.
    pub implicit: BTreeSet<usize>,
    /// What the conversion is told about, in the order it is found.
    pub warnings: Vec<String>,
}

impl Analysis {
    /// Whether the value of a quantity never changes.
    pub fn is_constant(&self, quantity: usize) -> bool {
        self.constants.contains(&quantity) || self.computed.contains(&quantity)
    }
}

/// What an equation can determine: the value of a quantity or the rate of
/// a state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Candidate {
    /// The rate of change of a state.
    Rate(usize),
    /// The value of a quantity.
    Value(usize),
}

impl Candidate {
    /// The quantity it determines, whose value no other equation may give.
    fn quantity(self) -> usize {
        match self {
            Self::Rate(quantity) | Self::Value(quantity) => quantity,
        }
    }
}

/// Take a candidate: the equation of the quantity, and its kind.
fn take(
    analysis: &mut Analysis,
    determined: &mut HashMap<usize, (usize, bool)>,
    candidate: Candidate,
    component: usize,
    index: usize,
) {
    let kind = match candidate {
        Candidate::Rate(state) => {
            analysis.states.insert(state);
            EquationKind::Rate { state }
        }
        Candidate::Value(target) => EquationKind::Assignment { target },
    };
    determined.insert(
        candidate.quantity(),
        (
            analysis.equations.len(),
            matches!(candidate, Candidate::Rate(_)),
        ),
    );
    analysis.equations.push(Equation {
        component,
        index,
        kind,
    });
}

/// The quantity of a variable of a component by its name.
fn quantity_of(model: &Model, ids: &Ids, component: usize, name: &str) -> Result<usize, MathError> {
    ids.quantity_of(model, component, name)
        .ok_or_else(|| MathError::Variable {
            variable: name.to_string(),
            component: model.components[component].name.clone(),
        })
}

/// The variable a node is the derivative of, with the variable of
/// integration and the order.
fn derivative(node: &Node) -> Option<(&str, &str, u32)> {
    match node {
        Node::Derivative {
            variable,
            degree,
            expression,
        } => match expression.as_ref() {
            Node::Identifier(name) => Some((name, variable, *degree)),
            _ => None,
        },
        _ => None,
    }
}

/// The quantity a side of an equation is, when the side is one variable.
fn single(
    node: &Node,
    model: &Model,
    ids: &Ids,
    component: usize,
) -> Result<Option<usize>, MathError> {
    match node {
        Node::Identifier(name) => {
            let quantity =
                ids.quantity_of(model, component, name)
                    .ok_or_else(|| MathError::Variable {
                        variable: name.clone(),
                        component: model.components[component].name.clone(),
                    })?;
            Ok(Some(quantity))
        }
        _ => Ok(None),
    }
}

/// Read what the equations of a model determine.
///
/// # Arguments
///
/// * `model` - the model, with its imports resolved.
/// * `ids` - the quantities of the model.
///
/// # Errors
///
/// Returns the first [`AnalysisError`] of the equations.
pub fn analyse(model: &Model, ids: &Ids) -> Result<Analysis, AnalysisError> {
    let mut analysis = Analysis::default();
    let mut voi_name: Option<String> = None;
    // every equation with the quantities it could determine, the value of
    // a variable or the rate of a state
    let mut pending: Vec<(usize, usize, Vec<Candidate>)> = Vec::new();
    // the equation which determines a quantity, and whether it is its rate
    let mut determined: HashMap<usize, (usize, bool)> = HashMap::new();

    if let Some(units) = model
        .units
        .iter()
        .chain(
            model
                .components
                .iter()
                .flat_map(|component| &component.units),
        )
        .find(|units| units.import.is_some())
    {
        return Err(AnalysisError::ImportedUnits(units.name.clone()));
    }

    for (index, component) in model.components.iter().enumerate() {
        if component.import.is_some() && component.variables.is_empty() {
            return Err(AnalysisError::Imported(component.name.clone()));
        }
        for (position, node) in component.math.iter().enumerate() {
            let Some((left, right)) = equality(node) else {
                // a child of `<math>` which is no equality is no rule of
                // the SBML model either, e.g. the annotation of the
                // uncertainty of a variable, which some models of the
                // Physiome Model Repository carry
                analysis.warnings.push(format!(
                    "the mathematics of component '{}' holds something which is no \
                     equation, which the conversion leaves out",
                    component.name
                ));
                continue;
            };
            let mut candidates = Vec::new();
            for side in [left, right] {
                if let Some((state, of, degree)) = derivative(side) {
                    if degree != 1 {
                        return Err(AnalysisError::HigherOrder(degree));
                    }
                    let integration = quantity_of(model, ids, index, of)?;
                    match analysis.voi {
                        Some(previous) if previous != integration => {
                            return Err(AnalysisError::SeveralVoi {
                                first: voi_name.unwrap_or_default(),
                                second: of.to_string(),
                            });
                        }
                        _ => {
                            analysis.voi = Some(integration);
                            voi_name = Some(of.to_string());
                        }
                    }
                    candidates.push(Candidate::Rate(quantity_of(model, ids, index, state)?));
                } else if let Some(quantity) = single(side, model, ids, index)? {
                    candidates.push(Candidate::Value(quantity));
                }
            }
            pending.push((index, position, candidates));
        }
    }

    // the variable of integration is no unknown of an equation
    let voi = analysis.voi;
    for (_, _, candidates) in &mut pending {
        candidates.retain(
            |candidate| !matches!(candidate, Candidate::Value(quantity) if Some(*quantity) == voi),
        );
    }

    // assign every equation one quantity, the equations which can
    // determine one only first: `J = d x / d t` determines `J` when
    // another equation gives the rate of `x`, and the rate of `x` when
    // none does
    let mut open: Vec<usize> = (0..pending.len()).collect();
    loop {
        let mut again = Vec::new();
        let mut progress = false;
        for position in open {
            let (component, index, candidates) = &pending[position];
            let free: Vec<Candidate> = candidates
                .iter()
                .copied()
                .filter(|candidate| !determined.contains_key(&candidate.quantity()))
                .collect();
            if free.len() == 1 {
                take(&mut analysis, &mut determined, free[0], *component, *index);
                progress = true;
            } else {
                again.push(position);
            }
        }
        open = again;
        if !progress {
            break;
        }
    }
    for position in open {
        let (component, index, candidates) = &pending[position];
        let free = candidates
            .iter()
            .copied()
            .find(|candidate| !determined.contains_key(&candidate.quantity()));
        match free {
            Some(candidate) => take(
                &mut analysis,
                &mut determined,
                candidate,
                *component,
                *index,
            ),
            None => analysis.equations.push(Equation {
                component: *component,
                index: *index,
                kind: EquationKind::Algebraic,
            }),
        }
    }

    // a rate equation which uses the rate of another state writes that
    // rate as `rateOf`, which SBML reads: a cycle of them gives no rate
    // at all, so it is refused instead of written
    let mut rate_edges: Vec<(usize, Vec<usize>)> = Vec::new();
    for equation in &analysis.equations {
        let EquationKind::Rate { state } = equation.kind else {
            continue;
        };
        let node = &model.components[equation.component].math[equation.index];
        let Some((left, right)) = equality(node) else {
            continue;
        };
        // the rate of another state is used by the right hand side of the
        // equation, the side which is not the derivative
        let side = if derivative(left).is_some() {
            right
        } else {
            left
        };
        let mut names = Vec::new();
        math_rates(side, &mut names);
        let used = names
            .iter()
            .filter_map(|name| ids.quantity_of(model, equation.component, name))
            .filter(|quantity| analysis.states.contains(quantity))
            .collect();
        rate_edges.push((state, used));
    }
    if let Some((first, second)) = first_cycle(&rate_edges) {
        return Err(AnalysisError::ImplicitRates {
            first: variable_name(model, ids, first),
            second: variable_name(model, ids, second),
        });
    }

    // an equation which determines a variable from a variable its own
    // equation determines is implicit: the two are solved together, which
    // SBML writes as algebraic rules, as the analyser of libcellml reads
    // such a pair as one implicit system
    let mut assignment_edges: Vec<(usize, Vec<usize>)> = Vec::new();
    for equation in &analysis.equations {
        let EquationKind::Assignment { target } = equation.kind else {
            continue;
        };
        let node = &model.components[equation.component].math[equation.index];
        let Some((left, right)) = equality(node) else {
            continue;
        };
        // what the equation computes the target from, the side which is
        // not the target itself
        let side = if single(left, model, ids, equation.component)? == Some(target) {
            right
        } else {
            left
        };
        let mut names = Vec::new();
        variables(side, &mut names);
        let used = names
            .iter()
            .filter_map(|name| ids.quantity_of(model, equation.component, name))
            .filter(|quantity| determined.contains_key(quantity))
            .filter(|quantity| !analysis.states.contains(quantity))
            .collect();
        assignment_edges.push((target, used));
    }
    for target in cyclic(&assignment_edges) {
        determined.remove(&target);
        for equation in &mut analysis.equations {
            if equation.kind == (EquationKind::Assignment { target }) {
                equation.kind = EquationKind::Algebraic;
            }
        }
    }

    // the unknowns of the implicit equations, which are no constants
    for equation in &analysis.equations {
        if equation.kind != EquationKind::Algebraic {
            continue;
        }
        let node = &model.components[equation.component].math[equation.index];
        let mut names = Vec::new();
        variables(node, &mut names);
        let mut unknowns = 0;
        for name in names {
            let Some(quantity) = ids.quantity_of(model, equation.component, &name) else {
                continue;
            };
            if Some(quantity) == voi
                || analysis.states.contains(&quantity)
                || determined.contains_key(&quantity)
            {
                continue;
            }
            if analysis.implicit.insert(quantity) {
                unknowns += 1;
            }
        }
        if unknowns == 0 {
            analysis.warnings.push(format!(
                "the implicit equation of component '{}' has no unknown of its own",
                model.components[equation.component].name
            ));
        }
    }

    // what no equation determines is a constant, what an equation computes
    // from constants only is one as well
    for quantity in 0..ids.len() {
        if Some(quantity) == voi
            || analysis.states.contains(&quantity)
            || determined.contains_key(&quantity)
            || analysis.implicit.contains(&quantity)
        {
            continue;
        }
        analysis.constants.insert(quantity);
    }
    let assignments: Vec<(usize, usize)> = analysis
        .equations
        .iter()
        .filter_map(|equation| match equation.kind {
            EquationKind::Assignment { target } => Some((target, equation.component)),
            _ => None,
        })
        .collect();
    let mut again = true;
    while again {
        again = false;
        for (target, component) in &assignments {
            if analysis.computed.contains(target) {
                continue;
            }
            let equation = analysis.equations[determined[target].0];
            let node = &model.components[equation.component].math[equation.index];
            let mut names = Vec::new();
            variables(node, &mut names);
            let constant = names.iter().all(|name| {
                match ids.quantity_of(model, *component, name) {
                    Some(quantity) => {
                        quantity == *target
                            || analysis.constants.contains(&quantity)
                            || analysis.computed.contains(&quantity)
                    }
                    // a variable the component does not have is reported
                    // when the equation is written
                    None => false,
                }
            });
            if constant {
                analysis.computed.insert(*target);
                again = true;
            }
        }
    }

    // a variable with a value and an equation is determined twice
    let mut reported: HashSet<usize> = HashSet::new();
    for quantity in determined.keys() {
        if analysis.computed.contains(quantity) || analysis.states.contains(quantity) {
            continue;
        }
        let members = ids.set(*quantity);
        let initialised = members.iter().any(|member| {
            model.components[member.component].variables[member.variable]
                .initial_value
                .is_some()
        });
        if initialised && reported.insert(*quantity) {
            analysis.warnings.push(format!(
                "variable '{}' has an initial value and an equation, the equation is used",
                variable_name(model, ids, *quantity)
            ));
        }
    }
    analysis.warnings.sort();
    Ok(analysis)
}

/// The name of the first variable of a quantity, for a message: the ids
/// are assigned after the analysis (`Ids::assign`), which decides them.
fn variable_name(model: &Model, ids: &Ids, quantity: usize) -> String {
    let reference = ids.set(quantity)[0];
    model.components[reference.component].variables[reference.variable]
        .name
        .clone()
}

/// The quantities of a dependency graph which no order resolves, the ones
/// in a cycle: what is left when every quantity whose dependencies are
/// resolved is taken away, round after round.
fn cyclic(edges: &[(usize, Vec<usize>)]) -> Vec<usize> {
    let mut open: Vec<(usize, Vec<usize>)> = edges.to_vec();
    loop {
        let resolved: HashSet<usize> = open
            .iter()
            .filter(|(_, used)| {
                used.iter()
                    .all(|quantity| !open.iter().any(|(target, _)| target == quantity))
            })
            .map(|(target, _)| *target)
            .collect();
        if resolved.is_empty() {
            let mut left: Vec<usize> = open.iter().map(|(target, _)| *target).collect();
            left.sort_unstable();
            left.dedup();
            return left;
        }
        open.retain(|(target, _)| !resolved.contains(target));
    }
}

/// Two quantities of a cycle of a dependency graph, `None` when the graph
/// has none.
fn first_cycle(edges: &[(usize, Vec<usize>)]) -> Option<(usize, usize)> {
    let left = cyclic(edges);
    let first = *left.first()?;
    let used = edges
        .iter()
        .find(|(target, _)| *target == first)
        .map(|(_, used)| used.clone())
        .unwrap_or_default();
    let second = used
        .into_iter()
        .find(|quantity| left.contains(quantity))
        .unwrap_or(first);
    Some((first, second))
}

/// The equation which determines a quantity, `None` for one no equation
/// determines.
pub fn equation_of(analysis: &Analysis, quantity: usize) -> Option<&Equation> {
    analysis
        .equations
        .iter()
        .find(|equation| match equation.kind {
            EquationKind::Rate { state } => state == quantity,
            EquationKind::Assignment { target } => target == quantity,
            EquationKind::Algebraic => false,
        })
}
