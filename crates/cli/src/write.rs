//! `cellml-write`: a CellML document written again as CellML 2.0.
//!
//! The command reads a CellML document of any version with the rust reader
//! and writes the model again with the writer of the same crate, next to the
//! document or where `-o` says, `-` for the standard output. It is the driver
//! of `scripts/cellml_write_parity.py`, which validates what it writes with
//! libcellml and compares what libcellml reads of the written document with
//! what it reads of the original.
//!
//! ```text
//! cellml-write model.cellml [-o written.cellml]
//! cellml-write -o - model.cellml
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
        eprintln!("usage: cellml-write <file.cellml> [more.cellml ...] [-o file.cellml|-]");
        return ExitCode::from(2);
    }
    let mut failed = false;
    for file in &files {
        let target = match out.as_deref() {
            Some("-") => None,
            Some(path) => Some(PathBuf::from(path)),
            None => Some(with_suffix(Path::new(file))),
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

/// The file the document is written to next to it, `<stem>.written.cellml`,
/// so the original is never overwritten.
fn with_suffix(path: &Path) -> PathBuf {
    let stem = path.file_stem().unwrap_or_default().to_string_lossy();
    path.with_file_name(format!("{stem}.written.cellml"))
}

/// Read one document and write it again.
fn write(path: &Path, target: Option<&Path>) -> Result<(), String> {
    let text = std::fs::read_to_string(path).map_err(|err| err.to_string())?;
    let document = cellml::read(&text).map_err(|err| err.to_string())?;
    let xml = document.to_xml();
    match target {
        Some(target) => std::fs::write(target, xml).map_err(|err| err.to_string()),
        None => {
            print!("{xml}");
            Ok(())
        }
    }
}
