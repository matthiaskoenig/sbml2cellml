//! `sbml-convert`: the CellML 2.0 of an SBML document.
//!
//! The command reads an SBML document of any level and version with the
//! reader of sbmlsim-core, converts it with `tocellml` and writes the CellML
//! next to the document or where `-o` says, `-` for the standard output.
//! What the conversion is told about, e.g. an initial value which is not
//! set, goes to the standard error. `scripts/sbml2cellml_parity.py` compares
//! what it writes with what the python converter writes for the same
//! document.
//!
//! ```text
//! sbml-convert model.xml [-o model.cellml]
//! sbml-convert -o - model.xml
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
        eprintln!("usage: sbml-convert <file.xml> [more.xml ...] [-o file.cellml|-]");
        return ExitCode::from(2);
    }
    let mut failed = false;
    for file in &files {
        let target = match out.as_deref() {
            Some("-") => None,
            Some(path) => Some(PathBuf::from(path)),
            None => Some(Path::new(file).with_extension("cellml")),
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
    let document = sbml::read(&text).map_err(|err| err.to_string())?;
    // the name of the model when it has none, as the python converter takes
    // the stem of the file
    let name = path
        .file_stem()
        .map(|stem| stem.to_string_lossy().to_string())
        .unwrap_or_else(|| "model".to_string());
    let conversion = tocellml::convert(&document, &name).map_err(|err| err.to_string())?;
    for warning in &conversion.warnings {
        eprintln!("{}: {warning}", path.display());
    }
    let xml = conversion.model.to_xml();
    match target {
        Some(target) => std::fs::write(target, xml).map_err(|err| err.to_string()),
        None => {
            print!("{xml}");
            Ok(())
        }
    }
}
