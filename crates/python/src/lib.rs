//! The python module of the rust reader and converter, `sbml2cellml._rust`.
//!
//! The module gives the python package the conversion of a CellML document
//! to SBML in the process, without a command line and without libcellml:
//! `sbml2cellml.rust` wraps it and `sbml2cellml.cellml2sbml` uses it.
//! Every function takes and returns text, so nothing of the rust model
//! crosses the boundary.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Convert a CellML document to SBML level 3 version 2.
///
/// # Arguments
///
/// * `text` - the CellML document.
///
/// # Returns
///
/// A tuple of the SBML document and what the conversion is told about,
/// e.g. a variable without a value.
///
/// # Errors
///
/// Raises `ValueError` with the message of the reader or the converter for
/// a document which cannot be read or converted.
#[pyfunction]
fn convert_cellml_to_sbml(py: Python<'_>, text: &str) -> PyResult<(String, Vec<String>)> {
    // the conversion touches nothing of python, so another thread of the
    // interpreter runs while it works
    py.detach(|| {
        let document = cellml::read(text).map_err(|err| PyValueError::new_err(err.to_string()))?;
        let conversion = convert::convert(&document.model)
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
        Ok((conversion.document.to_xml(), conversion.warnings))
    })
}

/// The version of CellML a document is written in, `"2.0"`, `"1.1"` or
/// `"1.0"`.
///
/// # Arguments
///
/// * `text` - the CellML document.
///
/// # Errors
///
/// Raises `ValueError` for a document which is no CellML model.
#[pyfunction]
fn cellml_version(text: &str) -> PyResult<String> {
    let document = cellml::read(text).map_err(|err| PyValueError::new_err(err.to_string()))?;
    Ok(match document.version {
        cellml::Version::V1_0 => "1.0",
        cellml::Version::V1_1 => "1.1",
        cellml::Version::V2_0 => "2.0",
    }
    .to_string())
}

/// Whether a document imports a component or units, which the conversion
/// needs resolved: the caller flattens such a document first.
///
/// # Arguments
///
/// * `text` - the CellML document.
///
/// # Errors
///
/// Raises `ValueError` for a document which is no CellML model.
#[pyfunction]
fn has_imports(text: &str) -> PyResult<bool> {
    let document = cellml::read(text).map_err(|err| PyValueError::new_err(err.to_string()))?;
    Ok(!document.model.imports.is_empty())
}

/// The module as the interpreter sees it.
#[pymodule]
fn _rust(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(convert_cellml_to_sbml, module)?)?;
    module.add_function(wrap_pyfunction!(cellml_version, module)?)?;
    module.add_function(wrap_pyfunction!(has_imports, module)?)?;
    Ok(())
}
