//! The XML of a CellML document: a model as a CellML 2.0 file.
//!
//! The writer is the counterpart of the reader, so a model which is read and
//! written again is the same model. It writes CellML 2.0, whatever version the
//! model was read from, which is the version the conversion of an SBML model
//! writes as well. A model of CellML 1.0 or 1.1 therefore moves to the later
//! version as it is written:
//!
//! - the `public_interface` and the `private_interface` of a variable become
//!   its `interface`, which says the same (`is_public`, `is_private`)
//! - a unit definition inside a component becomes one of the model, since
//!   CellML 2.0 holds them in the model only; a name which two components
//!   define differently is therefore written once, with the first definition
//! - `base_units="yes"` becomes a `<units>` element without a `<unit>` child,
//!   which is how CellML 2.0 declares new base units
//! - the `offset` of a unit is dropped, CellML 2.0 has none
//!
//! An element which the reader does not model ([`Node::Other`]) is written as
//! the empty element of its name: the reader keeps the name of such an element
//! only, so what was inside it is not written again.

use crate::math::{Constant, Node, Operator};
use crate::model::{
    CELLML_NS_2_0, Component, ComponentRef, Connection, Document, Model, Reset, Unit, Units,
    Variable, XLINK_NS,
};
use std::fmt::Write as _;

/// The namespace of content MathML.
pub const MATHML_NS: &str = "http://www.w3.org/1998/Math/MathML";

/// One level of indentation.
const INDENT: &str = "  ";

/// The units of the degree of a derivative, which CellML gives every number.
const DIMENSIONLESS: &str = "dimensionless";

impl Document {
    /// The XML of the model, a complete CellML 2.0 file.
    #[must_use]
    pub fn to_xml(&self) -> String {
        self.model.to_xml()
    }
}

impl Model {
    /// The XML of the model, a complete CellML 2.0 file.
    #[must_use]
    pub fn to_xml(&self) -> String {
        let mut out = String::new();
        out.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
        let _ = write!(out, "<model xmlns=\"{CELLML_NS_2_0}\"");
        if !self.imports.is_empty() {
            let _ = write!(out, " xmlns:xlink=\"{XLINK_NS}\"");
        }
        let _ = writeln!(out, " name=\"{}\">", escape(&self.name));
        for import in &self.imports {
            indent(&mut out, 1);
            let _ = writeln!(out, "<import xlink:href=\"{}\">", escape(&import.href));
            for item in &import.components {
                indent(&mut out, 2);
                let _ = writeln!(
                    out,
                    "<component name=\"{}\" component_ref=\"{}\"/>",
                    escape(&item.name),
                    escape(&item.reference)
                );
            }
            for item in &import.units {
                indent(&mut out, 2);
                let _ = writeln!(
                    out,
                    "<units name=\"{}\" units_ref=\"{}\"/>",
                    escape(&item.name),
                    escape(&item.reference)
                );
            }
            indent(&mut out, 1);
            out.push_str("</import>\n");
        }
        // the unit definitions of the model and the ones its components hold,
        // which CellML 2.0 has no place for; an import writes its own above
        let mut names: Vec<&str> = Vec::new();
        for units in self
            .units
            .iter()
            .chain(self.components.iter().flat_map(|c| c.units.iter()))
        {
            if units.import.is_some() || names.contains(&units.name.as_str()) {
                continue;
            }
            names.push(&units.name);
            write_units(&mut out, units, 1);
        }
        for component in &self.components {
            write_component(&mut out, component, 1);
        }
        for connection in &self.connections {
            write_connection(&mut out, connection, 1);
        }
        if !self.encapsulation.is_empty() {
            indent(&mut out, 1);
            out.push_str("<encapsulation>\n");
            for root in &self.encapsulation {
                write_component_ref(&mut out, root, 2);
            }
            indent(&mut out, 1);
            out.push_str("</encapsulation>\n");
        }
        out.push_str("</model>\n");
        out
    }
}

/// Write the indentation of a depth.
fn indent(out: &mut String, depth: usize) {
    for _ in 0..depth {
        out.push_str(INDENT);
    }
}

/// The text of a value of an attribute, with the five entities escaped.
fn escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for character in text.chars() {
        match character {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&apos;"),
            _ => out.push(character),
        }
    }
    out
}

/// The text of a number: the shortest form which reads back as the value.
///
/// A number of a `<cn>` element is written with [`write_number`], which has
/// the notation CellML 2.0 wants for an exponent and for a value which is no
/// number at all; this is the text of an attribute, of an exponent and of a
/// multiplier.
#[must_use]
pub fn number_text(value: f64) -> String {
    let text = format!("{value:?}");
    text.strip_suffix(".0").map_or(text.clone(), str::to_string)
}

/// A number as CellML 2.0 writes one: the text of a `<cn>` element, with the
/// `e-notation` of MathML for a value which needs an exponent
/// (`<cn type="e-notation">1<sep/>-7</cn>` is 1e-7, the text `1e-7` is no
/// number of CellML), and the elements of MathML for an infinity and for a
/// value which is no number, which a `<cn>` cannot hold.
fn write_number(out: &mut String, value: f64, units: &str, depth: usize) {
    indent(out, depth);
    if value.is_nan() {
        out.push_str("<notanumber/>\n");
        return;
    }
    if value.is_infinite() {
        if value > 0.0 {
            out.push_str("<infinity/>\n");
        } else {
            out.push_str("<apply><minus/><infinity/></apply>\n");
        }
        return;
    }
    let text = number_text(value);
    let units = escape(units);
    match text.split_once(['e', 'E']) {
        Some((mantissa, exponent)) => {
            let _ = writeln!(
                out,
                "<cn type=\"e-notation\" cellml:units=\"{units}\">{mantissa}<sep/>{exponent}</cn>"
            );
        }
        None => {
            let _ = writeln!(out, "<cn cellml:units=\"{units}\">{text}</cn>");
        }
    }
}

/// A unit definition and its units.
fn write_units(out: &mut String, units: &Units, depth: usize) {
    indent(out, depth);
    let _ = write!(out, "<units name=\"{}\"", escape(&units.name));
    // new base units are a definition without a unit of its own
    if units.units.is_empty() {
        out.push_str("/>\n");
        return;
    }
    out.push_str(">\n");
    for unit in &units.units {
        write_unit(out, unit, depth + 1);
    }
    indent(out, depth);
    out.push_str("</units>\n");
}

/// One unit of a unit definition; CellML 2.0 has no offset.
fn write_unit(out: &mut String, unit: &Unit, depth: usize) {
    indent(out, depth);
    let _ = write!(out, "<unit units=\"{}\"", escape(&unit.units));
    if let Some(prefix) = &unit.prefix {
        let _ = write!(out, " prefix=\"{}\"", escape(prefix));
    }
    if unit.exponent != 1.0 {
        let _ = write!(out, " exponent=\"{}\"", number_text(unit.exponent));
    }
    if unit.multiplier != 1.0 {
        let _ = write!(out, " multiplier=\"{}\"", number_text(unit.multiplier));
    }
    out.push_str("/>\n");
}

/// A component with its variables, its mathematics and its resets; an imported
/// component is written by its import, which holds its name.
fn write_component(out: &mut String, component: &Component, depth: usize) {
    if component.import.is_some() {
        return;
    }
    indent(out, depth);
    let _ = write!(out, "<component name=\"{}\"", escape(&component.name));
    if component.variables.is_empty() && component.math.is_empty() && component.resets.is_empty() {
        out.push_str("/>\n");
        return;
    }
    out.push_str(">\n");
    for variable in &component.variables {
        write_variable(out, variable, depth + 1);
    }
    if !component.math.is_empty() {
        write_math(out, &component.math, depth + 1);
    }
    for reset in &component.resets {
        write_reset(out, reset, depth + 1);
    }
    indent(out, depth);
    out.push_str("</component>\n");
}

/// A variable with its units, its initial value and its interface.
fn write_variable(out: &mut String, variable: &Variable, depth: usize) {
    indent(out, depth);
    let _ = write!(
        out,
        "<variable name=\"{}\" units=\"{}\"",
        escape(&variable.name),
        escape(&variable.units)
    );
    if let Some(initial) = &variable.initial_value {
        let _ = write!(out, " initial_value=\"{}\"", escape(initial));
    }
    // the two directions of CellML 1.0 and 1.1 say the same as the interface
    let interface = match (variable.is_public(), variable.is_private()) {
        (true, true) => Some("public_and_private"),
        (true, false) => Some("public"),
        (false, true) => Some("private"),
        (false, false) => None,
    };
    if let Some(interface) = interface {
        let _ = write!(out, " interface=\"{interface}\"");
    }
    out.push_str("/>\n");
}

/// A reset with the mathematics of its test value and of its reset value.
fn write_reset(out: &mut String, reset: &Reset, depth: usize) {
    indent(out, depth);
    let _ = writeln!(
        out,
        "<reset variable=\"{}\" test_variable=\"{}\" order=\"{}\">",
        escape(&reset.variable),
        escape(&reset.test_variable),
        reset.order
    );
    for (name, math) in [
        ("test_value", &reset.test_value),
        ("reset_value", &reset.reset_value),
    ] {
        if let Some(math) = math {
            indent(out, depth + 1);
            let _ = writeln!(out, "<{name}>");
            write_math(out, std::slice::from_ref(math), depth + 2);
            indent(out, depth + 1);
            let _ = writeln!(out, "</{name}>");
        }
    }
    indent(out, depth);
    out.push_str("</reset>\n");
}

/// A connection and the variables it maps.
fn write_connection(out: &mut String, connection: &Connection, depth: usize) {
    indent(out, depth);
    let _ = writeln!(
        out,
        "<connection component_1=\"{}\" component_2=\"{}\">",
        escape(&connection.component_1),
        escape(&connection.component_2)
    );
    for (first, second) in &connection.variables {
        indent(out, depth + 1);
        let _ = writeln!(
            out,
            "<map_variables variable_1=\"{}\" variable_2=\"{}\"/>",
            escape(first),
            escape(second)
        );
    }
    indent(out, depth);
    out.push_str("</connection>\n");
}

/// A component of the encapsulation with the components it encapsulates.
fn write_component_ref(out: &mut String, reference: &ComponentRef, depth: usize) {
    indent(out, depth);
    let _ = write!(
        out,
        "<component_ref component=\"{}\"",
        escape(&reference.component)
    );
    if reference.children.is_empty() {
        out.push_str("/>\n");
        return;
    }
    out.push_str(">\n");
    for child in &reference.children {
        write_component_ref(out, child, depth + 1);
    }
    indent(out, depth);
    out.push_str("</component_ref>\n");
}

/// The `<math>` element of the equations, with the namespace of CellML for the
/// units of the numbers.
fn write_math(out: &mut String, equations: &[Node], depth: usize) {
    indent(out, depth);
    let _ = writeln!(
        out,
        "<math xmlns=\"{MATHML_NS}\" xmlns:cellml=\"{CELLML_NS_2_0}\">"
    );
    for equation in equations {
        write_node(out, equation, depth + 1);
    }
    indent(out, depth);
    out.push_str("</math>\n");
}

/// One node of the mathematics.
fn write_node(out: &mut String, node: &Node, depth: usize) {
    match node {
        Node::Number { value, units } => {
            write_number(
                out,
                *value,
                units.as_deref().unwrap_or(DIMENSIONLESS),
                depth,
            );
        }
        Node::Identifier(name) => {
            indent(out, depth);
            let _ = writeln!(out, "<ci>{}</ci>", escape(name));
        }
        Node::Constant(constant) => {
            indent(out, depth);
            let _ = writeln!(out, "<{}/>", constant_name(*constant));
        }
        Node::Apply {
            operator,
            arguments,
        } => {
            indent(out, depth);
            out.push_str("<apply>\n");
            indent(out, depth + 1);
            let _ = writeln!(out, "<{}/>", operator_name(operator));
            for argument in arguments {
                write_node(out, argument, depth + 1);
            }
            indent(out, depth);
            out.push_str("</apply>\n");
        }
        Node::Piecewise { pieces, otherwise } => {
            indent(out, depth);
            out.push_str("<piecewise>\n");
            for (value, condition) in pieces {
                indent(out, depth + 1);
                out.push_str("<piece>\n");
                write_node(out, value, depth + 2);
                write_node(out, condition, depth + 2);
                indent(out, depth + 1);
                out.push_str("</piece>\n");
            }
            if let Some(otherwise) = otherwise {
                indent(out, depth + 1);
                out.push_str("<otherwise>\n");
                write_node(out, otherwise, depth + 2);
                indent(out, depth + 1);
                out.push_str("</otherwise>\n");
            }
            indent(out, depth);
            out.push_str("</piecewise>\n");
        }
        Node::Derivative {
            variable,
            degree,
            expression,
        } => {
            indent(out, depth);
            out.push_str("<apply>\n");
            indent(out, depth + 1);
            out.push_str("<diff/>\n");
            indent(out, depth + 1);
            out.push_str("<bvar>\n");
            indent(out, depth + 2);
            let _ = writeln!(out, "<ci>{}</ci>", escape(variable));
            if *degree != 1 {
                indent(out, depth + 2);
                let _ = writeln!(
                    out,
                    "<degree><cn cellml:units=\"{DIMENSIONLESS}\">{degree}</cn></degree>"
                );
            }
            indent(out, depth + 1);
            out.push_str("</bvar>\n");
            write_node(out, expression, depth + 1);
            indent(out, depth);
            out.push_str("</apply>\n");
        }
        Node::Qualifier { name, value } => {
            indent(out, depth);
            let _ = writeln!(out, "<{}>", escape(name));
            write_node(out, value, depth + 1);
            indent(out, depth);
            let _ = writeln!(out, "</{}>", escape(name));
        }
        Node::Other(name) => {
            indent(out, depth);
            let _ = writeln!(out, "<{}/>", escape(name));
        }
    }
}

/// The element name of a constant.
const fn constant_name(constant: Constant) -> &'static str {
    match constant {
        Constant::Pi => "pi",
        Constant::Exponentiale => "exponentiale",
        Constant::True => "true",
        Constant::False => "false",
        Constant::Infinity => "infinity",
        Constant::NotANumber => "notanumber",
    }
}

/// The element name of an operator.
fn operator_name(operator: &Operator) -> &str {
    match operator {
        Operator::Eq => "eq",
        Operator::Other(name) => name,
    }
}
