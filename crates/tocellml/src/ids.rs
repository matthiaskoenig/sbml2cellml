//! The CellML names of the elements of an SBML model.
//!
//! A name of CellML is an identifier which starts with a letter and holds
//! letters, digits and underscores, which is almost the `SId` of SBML: an id
//! may start with an underscore there, and such an id gets a leading `u` for
//! the units and `v` for a variable, as the python converter writes it.

use std::collections::HashSet;

/// Make a string a name of CellML: every character which is not a letter, a
/// digit or `_` becomes `_`, and a name which does not start with a letter
/// gets `start` in front of it.
#[must_use]
pub fn sanitize_name(name: &str, start: char) -> String {
    let mut sanitized: String = name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect();
    if !sanitized.starts_with(|first: char| first.is_ascii_alphabetic()) {
        sanitized.insert(0, start);
    }
    sanitized
}

/// Make a name unique among the used ones with a numeric suffix, and use it.
#[must_use]
pub fn unique_name(name: &str, used: &mut HashSet<String>) -> String {
    let mut candidate = name.to_string();
    let mut suffix = 2;
    while used.contains(&candidate) {
        candidate = format!("{name}_{suffix}");
        suffix += 1;
    }
    used.insert(candidate.clone());
    candidate
}
