//! Both conversions in a browser, `sbml2cellml.wasm`.
//!
//! The module is built for `wasm32-unknown-unknown` and has no dependency
//! on a host: it reads no file, resolves no import and calls nothing of the
//! outside, so the page which loads it converts a model without a server.
//! The online converter of the documentation is the caller,
//! `docs/javascripts/converter.js`.
//!
//! The interface is the C ABI of five functions, since the module needs no
//! binding generator and no tool beyond cargo. Every string crosses the
//! boundary as the bytes of its UTF-8 in the memory of the module:
//!
//! 1. `allocate(len)` gives a buffer of `len` bytes, which the caller
//!    writes the document into,
//! 2. `convert_cellml_to_sbml(pointer, len, out)` converts a CellML
//!    document and writes the pointer and the length of the result, which
//!    is JSON, to the two words at `out` (a buffer of two `usize`, 8 bytes
//!    of `allocate` for the 32 bit words of `wasm32`),
//! 3. `convert_sbml_to_cellml(pointer, len, name, name_len, out)` converts
//!    an SBML document the same way, with the name the CellML model takes
//!    when the SBML model has no id,
//! 4. `deallocate(pointer, len)` gives a buffer back, the result included:
//!    every buffer of the interface is a slice of bytes of exactly its
//!    length, so one function frees them all.
//!
//! The JSON of a conversion is `{"sbml": "...", "warnings": ["..."]}` or
//! `{"cellml": "...", "warnings": ["..."]}` and the JSON of a document
//! which cannot be read or converted is `{"error": "..."}`, so the caller
//! needs no second call for the error.
//!
//! ```
//! let json = sbml2cellml_wasm::convert(
//!     r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m"/>"#,
//! );
//! assert!(json.starts_with(r#"{"sbml":"#), "{json}");
//! let json = sbml2cellml_wasm::convert_to_cellml(
//!     r#"<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
//!        level="3" version="2"><model id="m"/></sbml>"#,
//!     "m",
//! );
//! assert!(json.starts_with(r#"{"cellml":"#), "{json}");
//! ```

use std::alloc::{Layout, alloc, dealloc};

/// The layout of a buffer of the interface: bytes, without an alignment.
///
/// # Panics
///
/// Panics for a length above `isize::MAX`, which no document reaches.
fn layout(len: usize) -> Layout {
    Layout::from_size_align(len, 1).expect("a layout of bytes")
}

/// A buffer of `len` bytes for the caller to write into.
///
/// The buffer is uninitialized and belongs to the caller until it gives it
/// back with [`deallocate`]. A length of zero gives the null pointer.
///
/// # Safety
///
/// The caller writes at most `len` bytes to the pointer and passes it to
/// [`convert_cellml_to_sbml`], [`convert_sbml_to_cellml`] or
/// [`deallocate`] only.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn allocate(len: usize) -> *mut u8 {
    if len == 0 {
        return std::ptr::null_mut();
    }
    // SAFETY: the layout has a non zero size
    unsafe { alloc(layout(len)) }
}

/// Give a buffer of [`allocate`], or the result of a conversion, back.
///
/// # Safety
///
/// `pointer` is a pointer of [`allocate`] or of a result written by
/// [`convert_cellml_to_sbml`], `len` is its length, and the caller does not
/// use it afterwards.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn deallocate(pointer: *mut u8, len: usize) {
    if pointer.is_null() || len == 0 {
        return;
    }
    // SAFETY: the pointer is a buffer of this module of that length
    unsafe { dealloc(pointer, layout(len)) }
}

/// Convert the document of `len` bytes at `pointer` and write the pointer
/// and the length of the JSON of the conversion to the two words at `out`.
///
/// The caller reads the JSON from the memory of the module and gives it
/// back with [`deallocate`].
///
/// # Safety
///
/// `pointer` holds `len` readable bytes and `out` two writable words,
/// both of [`allocate`].
#[unsafe(no_mangle)]
pub unsafe extern "C" fn convert_cellml_to_sbml(pointer: *const u8, len: usize, out: *mut usize) {
    // SAFETY: the caller passes a buffer of that length
    let bytes = unsafe { std::slice::from_raw_parts(pointer, len) };
    let json = match std::str::from_utf8(bytes) {
        Ok(text) => convert(text),
        Err(_) => error("the document is not UTF-8 text"),
    };
    // SAFETY: the caller passes two words of memory
    unsafe { write_result(json, out) };
}

/// Convert the SBML document of `len` bytes at `pointer` and write the
/// pointer and the length of the JSON of the conversion to the two words at
/// `out`.
///
/// The caller reads the JSON from the memory of the module and gives it
/// back with [`deallocate`].
///
/// # Safety
///
/// `pointer` holds `len` readable bytes, `name` holds `name_len` readable
/// bytes and `out` two writable words, all of [`allocate`].
#[unsafe(no_mangle)]
pub unsafe extern "C" fn convert_sbml_to_cellml(
    pointer: *const u8,
    len: usize,
    name: *const u8,
    name_len: usize,
    out: *mut usize,
) {
    // SAFETY: the caller passes buffers of those lengths
    let bytes = unsafe { std::slice::from_raw_parts(pointer, len) };
    let name_bytes = unsafe { std::slice::from_raw_parts(name, name_len) };
    let json = match (std::str::from_utf8(bytes), std::str::from_utf8(name_bytes)) {
        (Ok(text), Ok(name)) => convert_to_cellml(text, name),
        _ => error("the document is not UTF-8 text"),
    };
    // SAFETY: the caller passes two words of memory
    unsafe { write_result(json, out) };
}

/// Write the JSON of a conversion to the two words at `out`, as a buffer
/// the caller gives back with [`deallocate`].
///
/// # Safety
///
/// `out` holds two writable words of [`allocate`].
unsafe fn write_result(json: String, out: *mut usize) {
    let result = json.into_bytes().into_boxed_slice();
    let length = result.len();
    let result = Box::into_raw(result).cast::<u8>();
    // SAFETY: the caller passes two words of memory
    unsafe {
        out.write_unaligned(result as usize);
        out.add(1).write_unaligned(length);
    }
}

/// The JSON of the conversion of an SBML document: the CellML and the
/// warnings, or the error of the reader or the converter.
///
/// # Arguments
///
/// * `text` - the SBML document of any level and version.
/// * `name` - the name of the CellML model when the SBML model has no id.
#[must_use]
pub fn convert_to_cellml(text: &str, name: &str) -> String {
    let document = match sbml::read(text) {
        Ok(document) => document,
        Err(err) => return error(&err.to_string()),
    };
    match tocellml::convert(&document, name) {
        Ok(conversion) => {
            let warnings: Vec<String> = conversion
                .warnings
                .iter()
                .map(|warning| quoted(warning))
                .collect();
            format!(
                "{{\"cellml\":{},\"warnings\":[{}]}}",
                quoted(&conversion.model.to_xml()),
                warnings.join(",")
            )
        }
        Err(err) => error(&err.to_string()),
    }
}

/// The JSON of the conversion of a document: the SBML and the warnings, or
/// the error of the reader or the converter.
///
/// # Arguments
///
/// * `text` - the CellML document.
#[must_use]
pub fn convert(text: &str) -> String {
    let document = match cellml::read(text) {
        Ok(document) => document,
        Err(err) => return error(&err.to_string()),
    };
    if !document.model.imports.is_empty() {
        return error(
            "the document imports a component or units, which the \
             converter of the browser does not resolve: convert it with \
             the python package",
        );
    }
    match convert::convert(&document.model) {
        Ok(conversion) => {
            let warnings: Vec<String> = conversion
                .warnings
                .iter()
                .map(|warning| quoted(warning))
                .collect();
            format!(
                "{{\"sbml\":{},\"warnings\":[{}]}}",
                quoted(&conversion.document.to_xml()),
                warnings.join(",")
            )
        }
        Err(err) => error(&err.to_string()),
    }
}

/// The JSON of an error.
fn error(message: &str) -> String {
    format!("{{\"error\":{}}}", quoted(message))
}

/// A string as a JSON string, with the quotes.
fn quoted(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    out.push('"');
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            character if (character as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", character as u32));
            }
            character => out.push(character),
        }
    }
    out.push('"');
    out
}
