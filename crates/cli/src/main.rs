//! `cellml-info`: what the rust reader reads of a CellML document, as JSON.
//!
//! The summary is the structure of the model, not its mathematics: the
//! version, the unit definitions, the components with their variables,
//! the connections, the encapsulation, the imports and the equivalence
//! sets. `scripts/cellml_parity.py` compares it with what libcellml reads
//! of the same document, so the two readers are measured against each
//! other over the models of the Physiome check.
//!
//! ```text
//! cellml-info model.cellml [more.cellml ...]
//! ```

use cellml::{Document, Model, VariableRef};
use std::path::Path;
use std::process::ExitCode;

fn main() -> ExitCode {
    let files: Vec<String> = std::env::args().skip(1).collect();
    if files.is_empty() {
        eprintln!("usage: cellml-info <file.cellml> [more.cellml ...]");
        return ExitCode::from(2);
    }
    let mut summaries = Vec::new();
    let mut failed = false;
    for file in &files {
        match summary(Path::new(file)) {
            Ok(text) => summaries.push(text),
            Err(message) => {
                eprintln!("{file}: {message}");
                failed = true;
            }
        }
    }
    println!("[{}]", summaries.join(","));
    if failed {
        ExitCode::FAILURE
    } else {
        ExitCode::SUCCESS
    }
}

/// The summary of one document.
fn summary(path: &Path) -> Result<String, String> {
    let text = std::fs::read_to_string(path).map_err(|err| err.to_string())?;
    let document = cellml::read(&text).map_err(|err| err.to_string())?;
    Ok(document_json(path, &document))
}

/// The JSON of a document.
fn document_json(path: &Path, document: &Document) -> String {
    let model = &document.model;
    let version = match document.version {
        cellml::Version::V1_0 => "1.0",
        cellml::Version::V1_1 => "1.1",
        cellml::Version::V2_0 => "2.0",
    };
    let units = list(model.units.iter().map(|units| string(&units.name)));
    let components = list(model.components.iter().map(component_json));
    let connections = list(model.connections.iter().map(|connection| {
        object([
            (
                "components",
                list([
                    string(&connection.component_1),
                    string(&connection.component_2),
                ]),
            ),
            (
                "variables",
                list(
                    connection
                        .variables
                        .iter()
                        .map(|(one, other)| list([string(one), string(other)])),
                ),
            ),
        ])
    }));
    let encapsulation = list(
        model
            .encapsulation_parents()
            .iter()
            .map(|(child, parent)| list([string(child), string(parent)])),
    );
    let imports = list(model.imports.iter().map(|import| {
        object([
            ("href", string(&import.href)),
            (
                "components",
                list(
                    import
                        .components
                        .iter()
                        .map(|item| list([string(&item.name), string(&item.reference)])),
                ),
            ),
            (
                "units",
                list(
                    import
                        .units
                        .iter()
                        .map(|item| list([string(&item.name), string(&item.reference)])),
                ),
            ),
        ])
    }));
    let sets = list(cellml::equivalence_sets(model).iter().map(|set| {
        list(
            set.iter()
                .map(|reference| string(&full_name(model, *reference))),
        )
    }));
    object([
        ("file", string(&path.display().to_string())),
        ("version", string(version)),
        ("name", string(&model.name)),
        ("units", units),
        ("components", components),
        ("connections", connections),
        ("encapsulation", encapsulation),
        ("imports", imports),
        ("equivalence_sets", sets),
    ])
}

/// The JSON of a component.
fn component_json(component: &cellml::Component) -> String {
    object([
        ("name", string(&component.name)),
        (
            "variables",
            list(component.variables.iter().map(|variable| {
                object([
                    ("name", string(&variable.name)),
                    ("units", string(&variable.units)),
                    (
                        "initial_value",
                        variable
                            .initial_value
                            .as_deref()
                            .map_or_else(|| "null".to_string(), string),
                    ),
                    ("public", boolean(variable.is_public())),
                    ("private", boolean(variable.is_private())),
                ])
            })),
        ),
        ("equations", component.math.len().to_string()),
        (
            "units",
            list(component.units.iter().map(|units| string(&units.name))),
        ),
    ])
}

/// The name of a variable with its component, `component/variable`.
fn full_name(model: &Model, reference: VariableRef) -> String {
    let component = &model.components[reference.component];
    format!(
        "{}/{}",
        component.name, component.variables[reference.variable].name
    )
}

/// A JSON object of the pairs.
fn object<const N: usize>(members: [(&str, String); N]) -> String {
    let members: Vec<String> = members
        .iter()
        .map(|(key, value)| format!("{}:{}", string(key), value))
        .collect();
    format!("{{{}}}", members.join(","))
}

/// A JSON array of the values.
fn list(values: impl IntoIterator<Item = String>) -> String {
    let values: Vec<String> = values.into_iter().collect();
    format!("[{}]", values.join(","))
}

/// A JSON string.
fn string(text: &str) -> String {
    let mut escaped = String::with_capacity(text.len() + 2);
    escaped.push('"');
    for character in text.chars() {
        match character {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            control if (control as u32) < 0x20 => {
                escaped.push_str(&format!("\\u{:04x}", control as u32));
            }
            other => escaped.push(other),
        }
    }
    escaped.push('"');
    escaped
}

/// A JSON boolean.
fn boolean(value: bool) -> String {
    if value { "true" } else { "false" }.to_string()
}
