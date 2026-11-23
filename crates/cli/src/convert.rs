//! `cellml-convert`: the SBML level 3 version 2 of a CellML document.
//!
//! The command reads a CellML document with the rust reader, converts it
//! with `convert` and writes the SBML next to the document or where `-o`
//! says, `-` for the standard output. What the conversion is told about,
//! e.g. a variable without a value, goes to the standard error.
//! `scripts/cellml2sbml_parity.py` compares what it writes with what the
//! python converter writes for the same document.
//!
//! ```text
//! cellml-convert model.cellml [-o model.xml]
//! cellml-convert -o - model.cellml
//! ```

use std::path::{Path, PathBuf};
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut out: Option<String> = None;
    let mut files: Vec<String> = Vec::new();
    let mut arguments = std::env::args().skip(1);
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "-o" | "--out" => match arguments.next() {
                Some(value) => out = Some(value),
                None => {
                    eprintln!("-o needs a file");
                    return ExitCode::from(2);
                }
            },
            _ => files.push(argument),
        }
    }
    if files.is_empty() || (out.is_some() && files.len() > 1) {
        eprintln!("usage: cellml-convert <file.cellml> [more.cellml ...] [-o file.xml|-]");
        return ExitCode::from(2);
    }
    let mut failed = false;
    for file in &files {
        let target = match out.as_deref() {
            Some("-") => None,
            Some(path) => Some(PathBuf::from(path)),
            None => Some(Path::new(file).with_extension("xml")),
        };
        if let Err(message) = write(Path::new(file), target.as_deref()) {
            eprintln!("{file}: {message}");
            failed = true;
        }
    }
    if failed {
        ExitCode::FAILURE
    } else {
        ExitCode::SUCCESS
    }
}

/// Convert one document and write it.
fn write(path: &Path, target: Option<&Path>) -> Result<(), String> {
    let text = std::fs::read_to_string(path).map_err(|err| err.to_string())?;
    let document = cellml::read(&text).map_err(|err| err.to_string())?;
    let conversion = convert::convert(&document.model).map_err(|err| err.to_string())?;
    for warning in &conversion.warnings {
        eprintln!("{}: {warning}", path.display());
    }
    let xml = conversion.document.to_xml();
    match target {
        Some(target) => std::fs::write(target, xml).map_err(|err| err.to_string()),
        None => {
            print!("{xml}");
            Ok(())
        }
    }
}
