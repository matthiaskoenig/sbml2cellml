//! The equivalence sets of the variables of a model.
//!
//! A connection maps a variable of one component onto a variable of
//! another: the two are the same quantity, and a chain of connections
//! makes one set of them. The sets are what the conversion to SBML needs,
//! since every set becomes one parameter of the SBML model.

use crate::model::Model;

/// A variable of a model, by the index of its component and of itself.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct VariableRef {
    /// The index of the component in [`Model::components`].
    pub component: usize,
    /// The index of the variable in [`crate::Component::variables`].
    pub variable: usize,
}

/// The equivalence sets of the variables of a model.
///
/// Every variable of every component is in exactly one set, a variable
/// which no connection maps alone in a set of its own, so the sets are a
/// partition of the variables of the model. A connection which names a
/// component or a variable the model does not have is ignored, as
/// libcellml ignores it when it is not strict.
///
/// # Arguments
///
/// * `model` - a model.
///
/// # Returns
///
/// The sets, every one of them sorted and the sets by their first
/// variable, so the result of a model is the same on every run.
pub fn equivalence_sets(model: &Model) -> Vec<Vec<VariableRef>> {
    let mut offsets = Vec::with_capacity(model.components.len());
    let mut total = 0;
    for component in &model.components {
        offsets.push(total);
        total += component.variables.len();
    }
    let mut parent: Vec<usize> = (0..total).collect();
    for connection in &model.connections {
        let (Some(first), Some(second)) = (
            model.component(&connection.component_1),
            model.component(&connection.component_2),
        ) else {
            continue;
        };
        for (variable_1, variable_2) in &connection.variables {
            let (Some(one), Some(other)) = (
                model.components[first].variable(variable_1),
                model.components[second].variable(variable_2),
            ) else {
                continue;
            };
            union(&mut parent, offsets[first] + one, offsets[second] + other);
        }
    }

    let mut sets: Vec<Vec<VariableRef>> = vec![Vec::new(); total];
    for (component, offset) in offsets.iter().enumerate() {
        for variable in 0..model.components[component].variables.len() {
            let root = find(&mut parent, offset + variable);
            sets[root].push(VariableRef {
                component,
                variable,
            });
        }
    }
    let mut sets: Vec<Vec<VariableRef>> = sets.into_iter().filter(|set| !set.is_empty()).collect();
    for set in &mut sets {
        set.sort();
    }
    sets.sort();
    sets
}

/// The root of the set of `index`, with the path compressed.
fn find(parent: &mut [usize], index: usize) -> usize {
    let mut root = index;
    while parent[root] != root {
        root = parent[root];
    }
    let mut current = index;
    while parent[current] != root {
        let next = parent[current];
        parent[current] = root;
        current = next;
    }
    root
}

/// Put the sets of the two variables together.
fn union(parent: &mut [usize], one: usize, other: usize) {
    let (first, second) = (find(parent, one), find(parent, other));
    if first != second {
        // the smaller index wins, so the root of a set does not depend on
        // the order the connections are read in
        let (root, child) = if first < second {
            (first, second)
        } else {
            (second, first)
        };
        parent[child] = root;
    }
}
