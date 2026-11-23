//! The helpers of the tests of the conversion of an SBML model.

use cellml::{Node, Operator};
use tocellml::model::{Conversion, convert};

/// A level 3 version 2 document around the body of its model, with the
/// units of the model set, so the unit annotation can be complete.
pub fn level3(body: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" xmlns:sbml="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="m" substanceUnits="mole" timeUnits="second" extentUnits="mole"
         volumeUnits="litre" areaUnits="metre" lengthUnits="metre">{body}</model>
</sbml>"#
    )
}

/// The conversion of a document.
pub fn conversion(text: &str) -> Conversion {
    let document = sbml::read(text).expect("the document is read");
    convert(&document, "fallback").expect("the model is converted")
}

/// The variables of the component as `name = value [units]`, the value left
/// out for a variable an equation computes.
pub fn variables(conversion: &Conversion) -> Vec<String> {
    let component = &conversion.model.components[0];
    component
        .variables
        .iter()
        .map(|variable| match &variable.initial_value {
            Some(value) => format!("{} = {} [{}]", variable.name, value, variable.units),
            None => format!("{} [{}]", variable.name, variable.units),
        })
        .collect()
}

/// The equations of the component, every operator as a call of its name, so
/// that the structure of a formula is what the text says.
pub fn equations(conversion: &Conversion) -> Vec<String> {
    conversion.model.components[0]
        .math
        .iter()
        .map(text)
        .collect()
}

/// A formula as the text of the assertions.
pub fn text(node: &Node) -> String {
    match node {
        Node::Number { value, units } => match units.as_deref() {
            Some("dimensionless") | None => cellml::number_text(*value),
            Some(units) => format!("{}[{units}]", cellml::number_text(*value)),
        },
        Node::Identifier(name) => name.clone(),
        Node::Constant(constant) => format!("{constant:?}"),
        Node::Apply {
            operator: Operator::Eq,
            arguments,
        } => arguments.iter().map(text).collect::<Vec<_>>().join(" = "),
        Node::Apply {
            operator: Operator::Other(name),
            arguments,
        } => format!(
            "{name}({})",
            arguments.iter().map(text).collect::<Vec<_>>().join(", ")
        ),
        Node::Piecewise { pieces, otherwise } => {
            let mut parts: Vec<String> = pieces
                .iter()
                .map(|(value, condition)| format!("{} if {}", text(value), text(condition)))
                .collect();
            if let Some(otherwise) = otherwise {
                parts.push(format!("else {}", text(otherwise)));
            }
            format!("piecewise({})", parts.join(", "))
        }
        Node::Derivative {
            variable,
            degree,
            expression,
        } => format!("d{degree}({})/d({variable})", text(expression)),
        Node::Qualifier { name, value } => format!("{name}: {}", text(value)),
        Node::Other(name) => format!("<{name}>"),
    }
}

/// The names of the unit definitions of the model.
#[allow(dead_code, reason = "the tests of the events do not read the units")]
pub fn units(conversion: &Conversion) -> Vec<String> {
    conversion
        .model
        .units
        .iter()
        .map(|units| units.name.clone())
        .collect()
}
