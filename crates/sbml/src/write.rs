//! The XML of an SBML document.

use crate::math::Math;
use crate::model::{
    Document, Event, InitialAssignment, Model, Parameter, Rule, Unit, UnitDefinition,
};
use std::fmt::Write as _;

/// The namespace of SBML level 3 version 2 core.
pub const SBML_NS: &str = "http://www.sbml.org/sbml/level3/version2/core";

/// The namespace of content MathML.
pub const MATHML_NS: &str = "http://www.w3.org/1998/Math/MathML";

/// The `definitionURL` of the time of SBML.
const TIME_URL: &str = "http://www.sbml.org/sbml/symbols/time";

/// The `definitionURL` of the rate of change of SBML level 3 version 2.
const RATE_OF_URL: &str = "http://www.sbml.org/sbml/symbols/rateOf";

/// The name the `csymbol` of time is written with.
const TIME_NAME: &str = "time";

/// One level of indentation.
const INDENT: &str = "  ";

impl Document {
    /// The XML of the document, a complete SBML level 3 version 2 file.
    pub fn to_xml(&self) -> String {
        let mut out = String::new();
        out.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
        let _ = writeln!(out, "<sbml xmlns=\"{SBML_NS}\" level=\"3\" version=\"2\">");
        write_model(&mut out, &self.model, 1);
        out.push_str("</sbml>\n");
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

/// An attribute, when it has a value.
fn attribute(out: &mut String, name: &str, value: Option<&str>) {
    if let Some(value) = value {
        let _ = write!(out, " {name}=\"{}\"", escape(value));
    }
}

/// The text of a number: the shortest form which reads back as the value,
/// `NaN`, `INF` and `-INF` as SBML writes them.
pub fn number_text(value: f64) -> String {
    if value.is_nan() {
        return "NaN".to_string();
    }
    if value.is_infinite() {
        return if value > 0.0 { "INF" } else { "-INF" }.to_string();
    }
    let text = format!("{value:?}");
    text.strip_suffix(".0").map_or(text.clone(), str::to_string)
}

/// Whether the mathematics holds a number with units, which needs the
/// prefix of the SBML namespace on the `math` element.
fn has_units(math: &Math) -> bool {
    match math {
        Math::Number { units, .. } => units.is_some(),
        Math::Apply { arguments, .. } => arguments.iter().any(has_units),
        Math::Piecewise { pieces, otherwise } => {
            pieces
                .iter()
                .any(|(value, condition)| has_units(value) || has_units(condition))
                || otherwise.as_deref().is_some_and(has_units)
        }
        Math::Qualifier { value, .. } => has_units(value),
        Math::Identifier(_) | Math::Time | Math::RateOf(_) | Math::Constant(_) => false,
    }
}

/// Write the model and its lists.
fn write_model(out: &mut String, model: &Model, depth: usize) {
    indent(out, depth);
    out.push_str("<model");
    attribute(out, "id", model.id.as_deref());
    attribute(out, "name", model.name.as_deref());
    attribute(out, "timeUnits", model.time_units.as_deref());
    out.push_str(">\n");

    if !model.unit_definitions.is_empty() {
        indent(out, depth + 1);
        out.push_str("<listOfUnitDefinitions>\n");
        for definition in &model.unit_definitions {
            write_unit_definition(out, definition, depth + 2);
        }
        indent(out, depth + 1);
        out.push_str("</listOfUnitDefinitions>\n");
    }
    if !model.parameters.is_empty() {
        indent(out, depth + 1);
        out.push_str("<listOfParameters>\n");
        for parameter in &model.parameters {
            write_parameter(out, parameter, depth + 2);
        }
        indent(out, depth + 1);
        out.push_str("</listOfParameters>\n");
    }
    if !model.initial_assignments.is_empty() {
        indent(out, depth + 1);
        out.push_str("<listOfInitialAssignments>\n");
        for assignment in &model.initial_assignments {
            write_initial_assignment(out, assignment, depth + 2);
        }
        indent(out, depth + 1);
        out.push_str("</listOfInitialAssignments>\n");
    }
    if !model.rules.is_empty() {
        indent(out, depth + 1);
        out.push_str("<listOfRules>\n");
        for rule in &model.rules {
            write_rule(out, rule, depth + 2);
        }
        indent(out, depth + 1);
        out.push_str("</listOfRules>\n");
    }

    if !model.events.is_empty() {
        indent(out, depth + 1);
        out.push_str("<listOfEvents>\n");
        for event in &model.events {
            write_event(out, event, depth + 2);
        }
        indent(out, depth + 1);
        out.push_str("</listOfEvents>\n");
    }

    indent(out, depth);
    out.push_str("</model>\n");
}

/// Write an event, its trigger, its priority and its assignments.
fn write_event(out: &mut String, event: &Event, depth: usize) {
    indent(out, depth);
    let _ = writeln!(
        out,
        "<event id=\"{}\" useValuesFromTriggerTime=\"true\">",
        escape(&event.id)
    );
    indent(out, depth + 1);
    let _ = writeln!(
        out,
        "<trigger persistent=\"{}\" initialValue=\"{}\">",
        event.trigger.persistent, event.trigger.initial_value
    );
    write_math(out, &event.trigger.math, depth + 2);
    indent(out, depth + 1);
    out.push_str("</trigger>\n");
    if let Some(priority) = &event.priority {
        indent(out, depth + 1);
        out.push_str("<priority>\n");
        write_math(out, priority, depth + 2);
        indent(out, depth + 1);
        out.push_str("</priority>\n");
    }
    if !event.assignments.is_empty() {
        indent(out, depth + 1);
        out.push_str("<listOfEventAssignments>\n");
        for assignment in &event.assignments {
            indent(out, depth + 2);
            let _ = writeln!(
                out,
                "<eventAssignment variable=\"{}\">",
                escape(&assignment.variable)
            );
            write_math(out, &assignment.math, depth + 3);
            indent(out, depth + 2);
            out.push_str("</eventAssignment>\n");
        }
        indent(out, depth + 1);
        out.push_str("</listOfEventAssignments>\n");
    }
    indent(out, depth);
    out.push_str("</event>\n");
}

/// Write a unit definition and its units.
fn write_unit_definition(out: &mut String, definition: &UnitDefinition, depth: usize) {
    indent(out, depth);
    out.push_str("<unitDefinition");
    attribute(out, "id", Some(&definition.id));
    attribute(out, "name", definition.name.as_deref());
    out.push_str(">\n");
    indent(out, depth + 1);
    out.push_str("<listOfUnits>\n");
    for unit in &definition.units {
        write_unit(out, unit, depth + 2);
    }
    indent(out, depth + 1);
    out.push_str("</listOfUnits>\n");
    indent(out, depth);
    out.push_str("</unitDefinition>\n");
}

/// Write one unit of a unit definition.
fn write_unit(out: &mut String, unit: &Unit, depth: usize) {
    indent(out, depth);
    let _ = writeln!(
        out,
        "<unit kind=\"{}\" exponent=\"{}\" scale=\"{}\" multiplier=\"{}\"/>",
        unit.kind.name(),
        number_text(unit.exponent),
        unit.scale,
        number_text(unit.multiplier),
    );
}

/// Write a parameter.
fn write_parameter(out: &mut String, parameter: &Parameter, depth: usize) {
    indent(out, depth);
    out.push_str("<parameter");
    attribute(out, "id", Some(&parameter.id));
    attribute(out, "name", parameter.name.as_deref());
    attribute(out, "value", parameter.value.map(number_text).as_deref());
    attribute(out, "units", parameter.units.as_deref());
    let constant = if parameter.constant { "true" } else { "false" };
    let _ = writeln!(out, " constant=\"{constant}\"/>");
}

/// Write an initial assignment.
fn write_initial_assignment(out: &mut String, assignment: &InitialAssignment, depth: usize) {
    indent(out, depth);
    let _ = writeln!(
        out,
        "<initialAssignment symbol=\"{}\">",
        escape(&assignment.symbol)
    );
    write_math(out, &assignment.math, depth + 1);
    indent(out, depth);
    out.push_str("</initialAssignment>\n");
}

/// Write a rule.
fn write_rule(out: &mut String, rule: &Rule, depth: usize) {
    let (element, variable, math) = match rule {
        Rule::Assignment { variable, math } => ("assignmentRule", Some(variable), math),
        Rule::Rate { variable, math } => ("rateRule", Some(variable), math),
        Rule::Algebraic { math } => ("algebraicRule", None, math),
    };
    indent(out, depth);
    let _ = write!(out, "<{element}");
    attribute(out, "variable", variable.map(String::as_str));
    out.push_str(">\n");
    write_math(out, math, depth + 1);
    indent(out, depth);
    let _ = writeln!(out, "</{element}>");
}

/// Write a `math` element and its expression.
fn write_math(out: &mut String, math: &Math, depth: usize) {
    indent(out, depth);
    let _ = write!(out, "<math xmlns=\"{MATHML_NS}\"");
    if has_units(math) {
        let _ = write!(out, " xmlns:sbml=\"{SBML_NS}\"");
    }
    out.push_str(">\n");
    write_expression(out, math, depth + 1);
    indent(out, depth);
    out.push_str("</math>\n");
}

/// Write an expression.
fn write_expression(out: &mut String, math: &Math, depth: usize) {
    match math {
        Math::Number { value, units } => write_number(out, *value, units.as_deref(), depth),
        Math::Identifier(id) => {
            indent(out, depth);
            let _ = writeln!(out, "<ci>{}</ci>", escape(id));
        }
        Math::Time => {
            indent(out, depth);
            let _ = writeln!(
                out,
                "<csymbol encoding=\"text\" definitionURL=\"{TIME_URL}\">{TIME_NAME}</csymbol>"
            );
        }
        Math::Constant(constant) => {
            indent(out, depth);
            let _ = writeln!(out, "<{}/>", constant.name());
        }
        Math::Apply {
            operator,
            arguments,
        } => {
            indent(out, depth);
            out.push_str("<apply>\n");
            indent(out, depth + 1);
            let _ = writeln!(out, "<{operator}/>");
            for argument in arguments {
                write_expression(out, argument, depth + 1);
            }
            indent(out, depth);
            out.push_str("</apply>\n");
        }
        Math::RateOf(id) => {
            indent(out, depth);
            out.push_str("<apply>\n");
            indent(out, depth + 1);
            let _ = writeln!(
                out,
                "<csymbol encoding=\"text\" definitionURL=\"{RATE_OF_URL}\">rateOf</csymbol>"
            );
            indent(out, depth + 1);
            let _ = writeln!(out, "<ci>{}</ci>", escape(id));
            indent(out, depth);
            out.push_str("</apply>\n");
        }
        Math::Qualifier { name, value } => {
            indent(out, depth);
            let _ = writeln!(out, "<{name}>");
            write_expression(out, value, depth + 1);
            indent(out, depth);
            let _ = writeln!(out, "</{name}>");
        }
        Math::Piecewise { pieces, otherwise } => {
            indent(out, depth);
            out.push_str("<piecewise>\n");
            for (value, condition) in pieces {
                indent(out, depth + 1);
                out.push_str("<piece>\n");
                write_expression(out, value, depth + 2);
                write_expression(out, condition, depth + 2);
                indent(out, depth + 1);
                out.push_str("</piece>\n");
            }
            if let Some(otherwise) = otherwise {
                indent(out, depth + 1);
                out.push_str("<otherwise>\n");
                write_expression(out, otherwise, depth + 2);
                indent(out, depth + 1);
                out.push_str("</otherwise>\n");
            }
            indent(out, depth);
            out.push_str("</piecewise>\n");
        }
    }
}

/// Write a number: a real, or a mantissa and an exponent when the shortest
/// form of the value is in e notation, which a MathML real is not.
fn write_number(out: &mut String, value: f64, units: Option<&str>, depth: usize) {
    indent(out, depth);
    out.push_str("<cn");
    let text = number_text(value);
    let notation = text.split_once(['e', 'E']);
    if notation.is_some() {
        out.push_str(" type=\"e-notation\"");
    }
    if let Some(units) = units {
        let _ = write!(out, " sbml:units=\"{}\"", escape(units));
    }
    match notation {
        Some((mantissa, exponent)) => {
            let _ = writeln!(out, "> {mantissa} <sep/> {exponent} </cn>");
        }
        None => {
            let _ = writeln!(out, "> {text} </cn>");
        }
    }
}
