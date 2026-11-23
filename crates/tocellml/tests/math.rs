//! The mathematics of an SBML formula as the mathematics of CellML.

use cellml::{Constant, Node, Operator};
use sbml::math::Node as Sbml;
use sbml::{Model, Rule, read};
use tocellml::math::{Functions, MathError, Names, expression};
use tocellml::units::Units;

/// A document whose assignment rule carries the formula, with the elements
/// the formulas of the tests reference.
fn document(formula: &str, definitions: &str) -> (Model, Units) {
    let text = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" xmlns:sbml="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="m" substanceUnits="mole" timeUnits="second" extentUnits="mole" volumeUnits="litre">
    <listOfUnitDefinitions>
      <unitDefinition id="per_min">
        <listOfUnits><unit kind="second" exponent="-1" multiplier="60"/></listOfUnits>
      </unitDefinition>
    </listOfUnitDefinitions>
    {definitions}
    <listOfParameters>
      <parameter id="a" value="1" constant="true"/>
      <parameter id="b" value="2" constant="true"/>
      <parameter id="c" value="3" constant="true"/>
      <parameter id="k" value="1" constant="true"/>
      <parameter id="p" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="p">
        <math xmlns="http://www.w3.org/1998/Math/MathML">{formula}</math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"#
    );
    let document = read(&text).expect("the document is read");
    let units = Units::new(&document.model, document.level);
    (document.model, units)
}

/// The formula of the assignment rule of the model.
fn math_of(model: &Model) -> Sbml {
    match &model.rules[0] {
        Rule::Assignment { math, .. } => math.clone().expect("the rule has mathematics"),
        other => panic!("the rule is no assignment rule: {other:?}"),
    }
}

/// The formula as the mathematics of CellML, the ids as the names.
fn convert(formula: &str) -> Result<Node, MathError> {
    let (model, mut units) = document(formula, "");
    let names = Names {
        variable: &|id: &str| id.to_string(),
        time: "time",
    };
    expression(&math_of(&model), &names, &mut units)
}

/// A formula with its function definitions expanded and converted.
fn expanded(formula: &str, definitions: &str) -> Result<Node, MathError> {
    let (model, mut units) = document(formula, definitions);
    let functions = Functions::new(&model.function_definitions);
    let expanded = functions.expand(&math_of(&model))?;
    let names = Names {
        variable: &|id: &str| id.to_string(),
        time: "time",
    };
    expression(&expanded, &names, &mut units)
}

/// A variable of the CellML model.
fn variable(name: &str) -> Node {
    Node::Identifier(name.to_string())
}

/// A number of the CellML model.
fn number(value: f64, units: &str) -> Node {
    Node::Number {
        value,
        units: Some(units.to_string()),
    }
}

/// An operator applied to its arguments.
fn apply(operator: &str, arguments: Vec<Node>) -> Node {
    Node::Apply {
        operator: Operator::Other(operator.to_string()),
        arguments,
    }
}

#[test]
fn a_number_carries_the_units_of_cellml() {
    assert_eq!(
        convert(r#"<cn sbml:units="per_min">2</cn>"#),
        Ok(number(2.0, "per_min"))
    );
    // a number without units is dimensionless, as CellML requires units
    assert_eq!(convert("<cn>2</cn>"), Ok(number(2.0, "dimensionless")));
    assert_eq!(
        convert(r#"<cn type="e-notation" sbml:units="mole">1.5<sep/>-7</cn>"#),
        Ok(number(1.5e-7, "mole"))
    );
    // the units of a unit kind are the units of CellML of that kind
    assert_eq!(
        convert(r#"<cn sbml:units="litre">2</cn>"#),
        Ok(number(2.0, "litre"))
    );
}

#[test]
fn an_infinity_and_a_nan_are_the_elements_of_mathml() {
    assert_eq!(
        convert("<cn>INF</cn>"),
        Ok(Node::Constant(Constant::Infinity))
    );
    assert_eq!(
        convert("<cn>-INF</cn>"),
        Ok(apply("minus", vec![Node::Constant(Constant::Infinity)]))
    );
    assert_eq!(
        convert("<cn>NaN</cn>"),
        Ok(Node::Constant(Constant::NotANumber))
    );
    assert_eq!(
        convert("<infinity/>"),
        Ok(Node::Constant(Constant::Infinity))
    );
    assert_eq!(
        convert("<notanumber/>"),
        Ok(Node::Constant(Constant::NotANumber))
    );
}

#[test]
fn the_time_symbol_becomes_the_variable_of_integration() {
    let (model, mut units) = document(
        r#"<csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol>"#,
        "",
    );
    let names = Names {
        variable: &|id: &str| id.to_string(),
        time: "time_of_the_model",
    };
    assert_eq!(
        expression(&math_of(&model), &names, &mut units),
        Ok(variable("time_of_the_model"))
    );
}

#[test]
fn the_avogadro_symbol_becomes_the_number_sbml_defines() {
    let value = match convert(
        r#"<csymbol definitionURL="http://www.sbml.org/sbml/symbols/avogadro">N</csymbol>"#,
    ) {
        Ok(Node::Number {
            value,
            units: Some(units),
        }) => {
            assert_eq!(units, "dimensionless");
            value
        }
        other => panic!("the symbol is a number: {other:?}"),
    };
    assert!((value - 6.022_141_79e23).abs() < 1e8, "{value}");
}

#[test]
fn a_variable_is_named_as_the_model_names_it() {
    let (model, mut units) = document("<ci>k</ci>", "");
    let names = Names {
        variable: &|id: &str| format!("r1_{id}"),
        time: "time",
    };
    assert_eq!(
        expression(&math_of(&model), &names, &mut units),
        Ok(variable("r1_k"))
    );
}

#[test]
fn an_operator_keeps_its_element() {
    assert_eq!(
        convert("<apply><times/><ci>a</ci><ci>b</ci><ci>c</ci></apply>"),
        Ok(apply(
            "times",
            vec![variable("a"), variable("b"), variable("c")]
        ))
    );
    assert_eq!(
        convert("<apply><leq/><ci>a</ci><ci>b</ci></apply>"),
        Ok(apply("leq", vec![variable("a"), variable("b")]))
    );
    assert_eq!(
        convert("<apply><rem/><ci>a</ci><ci>b</ci></apply>"),
        Ok(apply("rem", vec![variable("a"), variable("b")]))
    );
}

#[test]
fn the_quotient_is_the_floor_of_the_division() {
    assert_eq!(
        convert("<apply><quotient/><ci>a</ci><ci>b</ci></apply>"),
        Ok(apply(
            "floor",
            vec![apply("divide", vec![variable("a"), variable("b")])]
        ))
    );
}

#[test]
fn an_implication_is_a_disjunction() {
    assert_eq!(
        convert("<apply><implies/><ci>a</ci><ci>b</ci></apply>"),
        Ok(apply(
            "or",
            vec![apply("not", vec![variable("a")]), variable("b")]
        ))
    );
}

#[test]
fn a_relation_of_three_arguments_is_the_conjunction_of_its_pairs() {
    assert_eq!(
        convert("<apply><lt/><ci>a</ci><ci>b</ci><ci>c</ci></apply>"),
        Ok(apply(
            "and",
            vec![
                apply("lt", vec![variable("a"), variable("b")]),
                apply("lt", vec![variable("b"), variable("c")]),
            ]
        ))
    );
}

#[test]
fn an_operator_of_less_than_two_arguments_is_its_value() {
    assert_eq!(
        convert("<apply><plus/></apply>"),
        Ok(number(0.0, "dimensionless"))
    );
    assert_eq!(
        convert("<apply><times/></apply>"),
        Ok(number(1.0, "dimensionless"))
    );
    assert_eq!(
        convert("<apply><and/></apply>"),
        Ok(Node::Constant(Constant::True))
    );
    assert_eq!(
        convert("<apply><or/></apply>"),
        Ok(Node::Constant(Constant::False))
    );
    assert_eq!(
        convert("<apply><plus/><ci>a</ci></apply>"),
        Ok(variable("a"))
    );
    assert_eq!(
        convert("<apply><times/><ci>a</ci></apply>"),
        Ok(variable("a"))
    );
    // an operator which takes one argument keeps it
    assert_eq!(
        convert("<apply><minus/><ci>a</ci></apply>"),
        Ok(apply("minus", vec![variable("a")]))
    );
    assert_eq!(
        convert("<apply><not/><ci>a</ci></apply>"),
        Ok(apply("not", vec![variable("a")]))
    );
}

#[test]
fn the_degree_of_a_root_and_the_base_of_a_logarithm_are_qualifiers() {
    assert_eq!(
        convert("<apply><root/><degree><cn>3</cn></degree><ci>a</ci></apply>"),
        Ok(apply(
            "root",
            vec![
                Node::Qualifier {
                    name: "degree".to_string(),
                    value: Box::new(number(3.0, "dimensionless")),
                },
                variable("a"),
            ]
        ))
    );
    // a square root is written without a degree
    assert_eq!(
        convert("<apply><root/><ci>a</ci></apply>"),
        Ok(apply("root", vec![variable("a")]))
    );
    assert_eq!(
        convert("<apply><log/><logbase><cn>2</cn></logbase><ci>a</ci></apply>"),
        Ok(apply(
            "log",
            vec![
                Node::Qualifier {
                    name: "logbase".to_string(),
                    value: Box::new(number(2.0, "dimensionless")),
                },
                variable("a"),
            ]
        ))
    );
    assert_eq!(
        convert("<apply><log/><ci>a</ci></apply>"),
        Ok(apply("log", vec![variable("a")]))
    );
    assert_eq!(
        convert("<apply><ln/><ci>a</ci></apply>"),
        Ok(apply("ln", vec![variable("a")]))
    );
}

#[test]
fn a_piecewise_keeps_its_pieces() {
    assert_eq!(
        convert(
            r#"<piecewise>
                 <piece><ci>a</ci><apply><lt/><ci>b</ci><ci>c</ci></apply></piece>
                 <otherwise><ci>b</ci></otherwise>
               </piecewise>"#
        ),
        Ok(Node::Piecewise {
            pieces: vec![(
                variable("a"),
                apply("lt", vec![variable("b"), variable("c")])
            )],
            otherwise: Some(Box::new(variable("b"))),
        })
    );
}

#[test]
fn the_constants_of_mathml_keep_their_element() {
    assert_eq!(convert("<true/>"), Ok(Node::Constant(Constant::True)));
    assert_eq!(convert("<false/>"), Ok(Node::Constant(Constant::False)));
    assert_eq!(convert("<pi/>"), Ok(Node::Constant(Constant::Pi)));
    assert_eq!(
        convert("<exponentiale/>"),
        Ok(Node::Constant(Constant::Exponentiale))
    );
}

#[test]
fn what_cellml_has_no_counterpart_for_is_refused() {
    assert_eq!(
        convert(
            r#"<apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol><ci>a</ci><ci>b</ci></apply>"#
        ),
        Err(MathError::Delay)
    );
    assert_eq!(
        convert(
            r#"<apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol><ci>a</ci></apply>"#
        ),
        Err(MathError::RateOf)
    );
    // a `<math>` element without an expression in it
    assert_eq!(convert(""), Err(MathError::Empty));
    assert_eq!(
        convert("<lambda><bvar><ci>x</ci></bvar><ci>x</ci></lambda>"),
        Err(MathError::Lambda)
    );
}

#[test]
fn a_call_of_a_function_definition_is_expanded() {
    let definitions = r#"<listOfFunctionDefinitions>
      <functionDefinition id="f">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci>x</ci></bvar>
            <bvar><ci>y</ci></bvar>
            <apply><times/><ci>x</ci><ci>y</ci></apply>
          </lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>"#;
    assert_eq!(
        expanded(
            r#"<apply><ci>f</ci><ci>a</ci><cn sbml:units="per_min">2</cn></apply>"#,
            definitions
        ),
        Ok(apply("times", vec![variable("a"), number(2.0, "per_min")]))
    );
    // the call of a function inside an argument is expanded as well
    assert_eq!(
        expanded(
            "<apply><ci>f</ci><apply><ci>f</ci><ci>a</ci><ci>b</ci></apply><ci>c</ci></apply>",
            definitions
        ),
        Ok(apply(
            "times",
            vec![
                apply("times", vec![variable("a"), variable("b")]),
                variable("c"),
            ]
        ))
    );
}

#[test]
fn a_call_of_a_function_which_calls_a_function_is_expanded() {
    let definitions = r#"<listOfFunctionDefinitions>
      <functionDefinition id="double">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci>x</ci></bvar>
            <apply><times/><cn>2</cn><ci>x</ci></apply>
          </lambda>
        </math>
      </functionDefinition>
      <functionDefinition id="quadruple">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci>x</ci></bvar>
            <apply><ci>double</ci><apply><ci>double</ci><ci>x</ci></apply></apply>
          </lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>"#;
    assert_eq!(
        expanded("<apply><ci>quadruple</ci><ci>a</ci></apply>", definitions),
        Ok(apply(
            "times",
            vec![
                number(2.0, "dimensionless"),
                apply("times", vec![number(2.0, "dimensionless"), variable("a")]),
            ]
        ))
    );
}

#[test]
fn a_call_which_cannot_be_expanded_is_refused() {
    let recursive = r#"<listOfFunctionDefinitions>
      <functionDefinition id="f">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda>
            <bvar><ci>x</ci></bvar>
            <apply><ci>f</ci><ci>x</ci></apply>
          </lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>"#;
    assert_eq!(
        expanded("<apply><ci>f</ci><ci>a</ci></apply>", recursive),
        Err(MathError::Recursive("f".to_string()))
    );
    let two = r#"<listOfFunctionDefinitions>
      <functionDefinition id="f">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda><bvar><ci>x</ci></bvar><apply><ci>g</ci><ci>x</ci></apply></lambda>
        </math>
      </functionDefinition>
      <functionDefinition id="g">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda><bvar><ci>x</ci></bvar><apply><ci>f</ci><ci>x</ci></apply></lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>"#;
    assert_eq!(
        expanded("<apply><ci>f</ci><ci>a</ci></apply>", two),
        Err(MathError::Recursive("f".to_string()))
    );
    let one = r#"<listOfFunctionDefinitions>
      <functionDefinition id="f">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda><bvar><ci>x</ci></bvar><ci>x</ci></lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>"#;
    assert_eq!(
        expanded("<apply><ci>f</ci><ci>a</ci><ci>b</ci></apply>", one),
        Err(MathError::Arguments {
            name: "f".to_string(),
            parameters: 1,
            arguments: 2,
        })
    );
    let empty = r#"<listOfFunctionDefinitions>
      <functionDefinition id="f"/>
    </listOfFunctionDefinitions>"#;
    assert_eq!(
        expanded("<apply><ci>f</ci><ci>a</ci></apply>", empty),
        Err(MathError::NoLambda("f".to_string()))
    );
    assert_eq!(
        expanded("<apply><ci>f</ci><ci>a</ci></apply>", ""),
        Err(MathError::Unknown("f".to_string()))
    );
}

#[test]
fn a_formula_without_a_call_is_expanded_to_itself() {
    let (model, _) = document("<apply><times/><ci>a</ci><ci>b</ci></apply>", "");
    let functions = Functions::new(&model.function_definitions);
    let math = math_of(&model);
    assert_eq!(functions.expand(&math), Ok(math));
}
