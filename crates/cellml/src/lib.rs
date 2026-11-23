//! Reader of CellML documents, of every version the repositories publish.
//!
//! [`read`] takes the text of a document and gives a [`Document`]: the
//! version it is written in and its [`Model`] with the unit definitions,
//! the components with their variables and their mathematics, the
//! connections, the encapsulation and the imports. A document of CellML
//! 1.0 or 1.1 is read as it is written, with its `public_interface` and
//! its groups of the relationship `encapsulation`, and gives the same
//! model as the document of CellML 2.0 of the same system, so what reads
//! the model afterwards does not know the version.
//!
//! The reader validates nothing and resolves nothing: it does no file
//! system access (an import keeps its `href`) and no network access, so
//! the crate builds for `wasm32-unknown-unknown` and runs in a browser.
//! [`equivalence_sets`] gives the variables a connection makes one
//! quantity, which the conversion to SBML needs.
//!
//! [`Model::to_xml`] writes a model as a CellML 2.0 document, whatever
//! version it was read from, so a model which is read and written again is
//! the same model and the conversion of an SBML model has a writer.
//!
//! ```
//! let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="decay">
//!   <component name="main">
//!     <variable name="x" units="dimensionless" initial_value="10"/>
//!   </component>
//! </model>"#;
//! let document = cellml::read(text).unwrap();
//! assert_eq!(document.version, cellml::Version::V2_0);
//! assert_eq!(document.model.components[0].variables[0].name, "x");
//! ```

mod equivalence;
pub mod math;
mod model;
mod write;

pub use equivalence::{VariableRef, equivalence_sets};
pub use math::{Constant, MathError, Node, Operator};
pub use model::{
    CELLML_NS_1_0, CELLML_NS_1_1, CELLML_NS_2_0, Component, ComponentRef, Connection, Direction,
    Document, Import, ImportRef, ImportedItem, Interface, Model, ReadError, Reset, Unit, Units,
    Variable, Version, XLINK_NS, read,
};
pub use write::{MATHML_NS, number_text};
