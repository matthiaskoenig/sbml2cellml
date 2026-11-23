//! The SBML ids of the variables of a CellML model.
//!
//! Every equivalence set of variables is one quantity and becomes one
//! parameter of the SBML model, as in the python converter: the id is the
//! name of the variable which represents the set, prefixed with the name of
//! its component when another set has a variable of that name, sanitized to
//! an SBML `SId` and made unique with a numeric suffix.
//!
//! The representative is the member of the set which the equation of the
//! quantity is written next to, else a member with an initial value, else
//! the first member, which is the variable the analyser of libcellml takes:
//! `Istim` of the component `stimulus_protocol`, which computes it, and not
//! `J_stim` of the component `membrane`, which uses it. The ids of the two
//! converters are the same that way, and the units and the initial value of
//! the parameter are the ones of the same variable. The names are assigned
//! after the analysis (`assign`), since the equations decide them.

use crate::analysis::{Analysis, equation_of};
use cellml::{Model, VariableRef, equivalence_sets};
use std::collections::{HashMap, HashSet};

/// Make a string an SBML `SId`: every character which is not a letter, a
/// digit or `_` becomes `_`, and a name which starts with a digit or is
/// empty gets a leading `_`.
pub fn sanitize_id(name: &str) -> String {
    let mut id: String = name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect();
    if !id.starts_with(|first: char| first.is_ascii_alphabetic() || first == '_') {
        id.insert(0, '_');
    }
    id
}

/// Make an id unique among the used ones with a numeric suffix, and use it.
pub fn unique_sid(id: &str, used: &mut HashSet<String>) -> String {
    let mut candidate = id.to_string();
    let mut suffix = 2;
    while used.contains(&candidate) {
        candidate = format!("{id}_{suffix}");
        suffix += 1;
    }
    used.insert(candidate.clone());
    candidate
}

/// The quantities of a model: the equivalence sets and their SBML ids.
#[derive(Debug, Clone)]
pub struct Ids {
    /// The equivalence sets, every one sorted, by the index of the quantity.
    sets: Vec<Vec<VariableRef>>,
    /// The id of every quantity.
    ids: Vec<String>,
    /// The quantity of every variable.
    quantities: HashMap<VariableRef, usize>,
    /// Every id taken, the reserved ones included.
    used: HashSet<String>,
}

impl Ids {
    /// The quantities of a model, without their ids: every equivalence set
    /// of variables is one quantity, which [`Ids::assign`] names once the
    /// equations are known.
    pub fn new(model: &Model) -> Self {
        let sets = equivalence_sets(model);
        let mut quantities = HashMap::new();
        for (index, set) in sets.iter().enumerate() {
            for variable in set {
                quantities.insert(*variable, index);
            }
        }
        Self {
            sets,
            ids: Vec::new(),
            quantities,
            used: HashSet::new(),
        }
    }

    /// Give every quantity its id, with the member of its set which
    /// represents it first.
    ///
    /// # Arguments
    ///
    /// * `model` - the model of the quantities.
    /// * `analysis` - its equations, which decide the representative.
    pub fn assign(&mut self, model: &Model, analysis: &Analysis) {
        for (quantity, set) in self.sets.iter_mut().enumerate() {
            let first = representative(model, analysis, set, quantity);
            set.swap(0, first);
        }
        let names: Vec<String> = self
            .sets
            .iter()
            .map(|set| {
                model.components[set[0].component].variables[set[0].variable]
                    .name
                    .clone()
            })
            .collect();
        let mut counts: HashMap<&String, usize> = HashMap::new();
        for name in &names {
            *counts.entry(name).or_default() += 1;
        }
        self.ids = Vec::with_capacity(self.sets.len());
        for (index, set) in self.sets.iter().enumerate() {
            let component = &model.components[set[0].component];
            let name = if counts.get(&names[index]).copied().unwrap_or_default() > 1 {
                format!("{}_{}", component.name, names[index])
            } else {
                names[index].clone()
            };
            self.ids
                .push(unique_sid(&sanitize_id(&name), &mut self.used));
        }
    }

    /// The number of quantities.
    pub fn len(&self) -> usize {
        self.sets.len()
    }

    /// Whether the model has no variable.
    pub fn is_empty(&self) -> bool {
        self.sets.is_empty()
    }

    /// The variables of a quantity, the first of them its representative.
    pub fn set(&self, quantity: usize) -> &[VariableRef] {
        &self.sets[quantity]
    }

    /// The id of a quantity.
    pub fn id(&self, quantity: usize) -> &str {
        &self.ids[quantity]
    }

    /// The quantity of a variable, `None` for a variable outside the model.
    pub fn quantity(&self, variable: VariableRef) -> Option<usize> {
        self.quantities.get(&variable).copied()
    }

    /// The quantity of a variable of a component by its name.
    pub fn quantity_of(&self, model: &Model, component: usize, name: &str) -> Option<usize> {
        let variable = model.components[component].variable(name)?;
        self.quantity(VariableRef {
            component,
            variable,
        })
    }

    /// Reserve an id outside the variables, for the model, and use it.
    pub fn reserve(&mut self, name: &str) -> String {
        unique_sid(&sanitize_id(name), &mut self.used)
    }
}

/// The member of an equivalence set which represents it: the one the
/// equation of the quantity is written next to, else one with an initial
/// value, else the first.
fn representative(
    model: &Model,
    analysis: &Analysis,
    set: &[VariableRef],
    quantity: usize,
) -> usize {
    if let Some(equation) = equation_of(analysis, quantity)
        && let Some(index) = set
            .iter()
            .position(|member| member.component == equation.component)
    {
        return index;
    }
    set.iter()
        .position(|member| {
            model.components[member.component].variables[member.variable]
                .initial_value
                .is_some()
        })
        .unwrap_or_default()
}
