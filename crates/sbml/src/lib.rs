//! The SBML level 3 version 2 document the converter of a CellML model
//! writes, and its XML.
//!
//! A CellML model has no reactions and no compartments, so a document holds
//! unit definitions, parameters, initial assignments and rules only. The
//! crate models what the converter needs and writes it: it parses nothing,
//! validates nothing and does no file system and no network access, so it
//! builds for the web.
//!
//! ```
//! use sbml::{Document, Math, Model, Parameter, Rule};
//!
//! let model = Model {
//!     id: Some("decay".to_string()),
//!     parameters: vec![Parameter {
//!         id: "x".to_string(),
//!         value: Some(10.0),
//!         units: Some("mole".to_string()),
//!         constant: false,
//!         ..Parameter::default()
//!     }],
//!     rules: vec![Rule::Rate {
//!         variable: "x".to_string(),
//!         math: Math::number(-1.0, Some("mole_per_second")),
//!     }],
//!     ..Model::default()
//! };
//! let xml = Document { model }.to_xml();
//! assert!(xml.contains("<rateRule variable=\"x\">"));
//! ```

mod math;
mod model;
mod write;

pub use write::{MATHML_NS, SBML_NS, number_text};

pub use math::{Constant, Math};
pub use model::{
    Document, Event, EventAssignment, InitialAssignment, Model, Parameter, Rule, Trigger, Unit,
    UnitDefinition, UnitKind,
};
