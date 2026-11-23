//! Conversion of an SBML model to a CellML 2.0 model, the counterpart of
//! `convert`, which converts a CellML model to SBML.
//!
//! The reader of the SBML document is `sbmlsim-sbml` of sbmlsim-core, which
//! reads every level and version of SBML core into the model of level 3, so
//! the conversion never sees a level. The CellML model it builds is written by
//! `cellml`, the crate which also reads CellML.
//!
//! [`Units`] is the first part: the unit definitions of the SBML model as
//! CellML units and the units of every element which becomes a variable.
//! [`is_annotated`] says whether the model states any units at all, which
//! decides whether the variables carry their units or are all
//! `dimensionless`, as in the python converter.

pub mod ids;
pub mod math;
pub mod units;

pub use math::{Functions, MathError, Names, expression};
pub use units::{DIMENSIONLESS, Units, is_annotated};
