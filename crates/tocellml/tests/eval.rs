//! The evaluation of the formulas of an SBML model at the start.

use sbml::math::Node as Sbml;
use tocellml::eval::{EvalError, Start};

/// A level 3 version 2 document around the body of its model.
fn level3(body: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="m">{body}</model>
</sbml>"#
    )
}

/// A formula as the content MathML of an SBML document reads it.
fn math(formula: &str) -> Sbml {
    let text = level3(&format!(
        r#"<listOfRules><assignmentRule variable="x">
             <math xmlns="http://www.w3.org/1998/Math/MathML">{formula}</math>
           </assignmentRule></listOfRules>"#
    ));
    let document = sbml::read(&text).expect("the document is read");
    match &document.model.rules[0] {
        sbml::Rule::Assignment { math, .. } => math.clone().expect("the rule has math"),
        rule => panic!("the rule is an assignment rule, not {rule:?}"),
    }
}

/// The value of a formula in a model without quantities.
fn value(formula: &str) -> f64 {
    let text = level3("");
    let document = sbml::read(&text).expect("the document is read");
    let (assignments, rules, rates) = (Vec::new(), Vec::new(), Vec::new());
    let mut start = Start::new(
        &document.model,
        &assignments,
        &rules,
        &rates,
        std::collections::HashMap::new(),
    );
    start
        .eval(&math(formula))
        .expect("the formula is evaluated")
}

/// A number as the content MathML of a formula.
fn n(value: &str) -> String {
    format!("<cn>{value}</cn>")
}

/// An operator applied to its arguments.
fn apply(op: &str, args: &[&str]) -> String {
    format!("<apply><{op}/>{}</apply>", args.concat())
}

#[test]
fn a_number_is_its_value() {
    assert_eq!(value(&n("2.5")), 2.5);
}

#[test]
fn the_operators_of_arithmetic() {
    assert_eq!(value(&apply("plus", &[&n("1"), &n("2"), &n("3")])), 6.0);
    assert_eq!(value(&apply("times", &[&n("2"), &n("3")])), 6.0);
    assert_eq!(value(&apply("minus", &[&n("2")])), -2.0);
    assert_eq!(value(&apply("minus", &[&n("5"), &n("2")])), 3.0);
    assert_eq!(value(&apply("divide", &[&n("3"), &n("2")])), 1.5);
    assert_eq!(value(&apply("power", &[&n("2"), &n("10")])), 1024.0);
    assert_eq!(value(&apply("abs", &[&n("-2")])), 2.0);
    assert_eq!(value(&apply("floor", &[&n("1.7")])), 1.0);
    assert_eq!(value(&apply("ceiling", &[&n("1.2")])), 2.0);
    assert_eq!(value(&apply("factorial", &[&n("5")])), 120.0);
    assert_eq!(value(&apply("max", &[&n("1"), &n("4"), &n("2")])), 4.0);
    assert_eq!(value(&apply("min", &[&n("1"), &n("4"), &n("2")])), 1.0);
}

#[test]
fn an_n_ary_operator_without_arguments_is_its_value() {
    assert_eq!(value(&apply("plus", &[])), 0.0);
    assert_eq!(value(&apply("times", &[])), 1.0);
}

#[test]
fn a_root_and_a_logarithm_take_their_qualifier() {
    assert_eq!(value(&apply("root", &[&n("16")])), 4.0);
    let cubic = "<degree><cn>3</cn></degree>";
    assert_eq!(value(&apply("root", &[cubic, &n("27")])), 3.0);
    assert_eq!(value(&apply("log", &[&n("1000")])), 3.0);
    let base = "<logbase><cn>2</cn></logbase>";
    assert_eq!(value(&apply("log", &[base, &n("8")])), 3.0);
    assert_eq!(value(&apply("ln", &[&apply("exp", &[&n("1")])])), 1.0);
}

#[test]
fn the_integer_division_truncates_towards_zero() {
    // the OpenMath dictionary of the MathML of SBML: the remainder has the
    // sign of the dividend
    assert_eq!(value(&apply("quotient", &[&n("-7"), &n("3")])), -2.0);
    assert_eq!(value(&apply("rem", &[&n("-7"), &n("3")])), -1.0);
    assert_eq!(value(&apply("quotient", &[&n("7"), &n("3")])), 2.0);
    assert_eq!(value(&apply("rem", &[&n("7"), &n("3")])), 1.0);
}

#[test]
fn a_relation_of_more_than_two_arguments_holds_for_every_pair() {
    assert_eq!(value(&apply("lt", &[&n("1"), &n("2"), &n("3")])), 1.0);
    assert_eq!(value(&apply("lt", &[&n("1"), &n("3"), &n("2")])), 0.0);
    assert_eq!(value(&apply("eq", &[&n("2"), &n("2")])), 1.0);
    assert_eq!(value(&apply("geq", &[&n("2"), &n("2")])), 1.0);
}

#[test]
fn the_logical_operators_take_a_value_which_is_not_zero_as_true() {
    assert_eq!(value(&apply("and", &[&n("1"), &n("2")])), 1.0);
    assert_eq!(value(&apply("and", &[&n("1"), &n("0")])), 0.0);
    assert_eq!(value(&apply("or", &[&n("0"), &n("3")])), 1.0);
    assert_eq!(value(&apply("xor", &[&n("1"), &n("1")])), 0.0);
    assert_eq!(value(&apply("not", &[&n("0")])), 1.0);
    assert_eq!(value(&apply("implies", &[&n("1"), &n("0")])), 0.0);
}

#[test]
fn a_piecewise_takes_the_first_piece_which_holds() {
    let piece =
        |value: &str, condition: &str| format!("<piece><cn>{value}</cn>{condition}</piece>");
    let formula = format!(
        "<piecewise>{}{}<otherwise><cn>3</cn></otherwise></piecewise>",
        piece("1", &apply("lt", &[&n("2"), &n("1")])),
        piece("2", &apply("lt", &[&n("1"), &n("2")])),
    );
    assert_eq!(value(&formula), 2.0);
    let otherwise = format!(
        "<piecewise>{}<otherwise><cn>3</cn></otherwise></piecewise>",
        piece("1", &apply("lt", &[&n("2"), &n("1")])),
    );
    assert_eq!(value(&otherwise), 3.0);
}

#[test]
fn a_piecewise_without_a_piece_which_holds_is_not_a_number() {
    let formula = format!(
        "<piecewise><piece><cn>1</cn>{}</piece></piecewise>",
        apply("lt", &[&n("2"), &n("1")])
    );
    assert!(value(&formula).is_nan());
}

#[test]
fn the_constants_and_the_symbols() {
    assert_eq!(value("<pi/>"), std::f64::consts::PI);
    assert_eq!(value("<exponentiale/>"), std::f64::consts::E);
    assert_eq!(value("<true/>"), 1.0);
    assert_eq!(value("<false/>"), 0.0);
    assert_eq!(value("<infinity/>"), f64::INFINITY);
    assert!(value("<notanumber/>").is_nan());
    let avogadro = r#"<csymbol definitionURL="http://www.sbml.org/sbml/symbols/avogadro"> avogadro </csymbol>"#;
    assert_eq!(value(avogadro), 6.022_141_79e23);
    let time = r#"<csymbol definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>"#;
    assert_eq!(value(time), 0.0, "time is zero at the start");
}

#[test]
fn a_delay_has_no_value() {
    let formula = format!(
        r#"<apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>{}{}</apply>"#,
        n("1"),
        n("2")
    );
    let text = level3("");
    let document = sbml::read(&text).expect("the document is read");
    let (assignments, rules, rates) = (Vec::new(), Vec::new(), Vec::new());
    let mut start = Start::new(
        &document.model,
        &assignments,
        &rules,
        &rates,
        std::collections::HashMap::new(),
    );
    assert_eq!(
        start.eval(&math(&formula)),
        Err(EvalError::Operator("delay".to_string()))
    );
}

/// The values of the quantities of a model, with the formulas of its rules.
fn values(body: &str) -> Vec<(String, Result<f64, EvalError>)> {
    let text = level3(body);
    let document = sbml::read(&text).expect("the document is read");
    let model = &document.model;
    let assignments: Vec<(String, Sbml)> = model
        .initial_assignments
        .iter()
        .filter_map(|assignment| {
            assignment
                .math
                .clone()
                .map(|math| (assignment.symbol.clone(), math))
        })
        .collect();
    let rules: Vec<(String, Sbml)> = model
        .rules
        .iter()
        .filter_map(|rule| match rule {
            sbml::Rule::Assignment { variable, math, .. } => {
                math.clone().map(|math| (variable.clone(), math))
            }
            _ => None,
        })
        .collect();
    let ids: Vec<String> = model
        .compartments
        .iter()
        .map(|compartment| compartment.id.clone())
        .chain(model.species.iter().map(|species| species.id.clone()))
        .chain(
            model
                .parameters
                .iter()
                .map(|parameter| parameter.id.clone()),
        )
        .collect();
    let rates = Vec::new();
    let mut start = Start::new(
        model,
        &assignments,
        &rules,
        &rates,
        std::collections::HashMap::new(),
    );
    ids.into_iter()
        .map(|id| {
            let value = start.value(&id);
            (id, value)
        })
        .collect()
}

#[test]
fn a_quantity_has_the_value_the_model_states() {
    let found = values(
        r#"<listOfCompartments><compartment id="c" size="2" constant="true"/></listOfCompartments>
           <listOfParameters><parameter id="p" value="3" constant="true"/></listOfParameters>"#,
    );
    assert_eq!(
        found,
        vec![("c".to_string(), Ok(2.0)), ("p".to_string(), Ok(3.0))]
    );
}

#[test]
fn a_quantity_without_a_value_has_the_one_a_simulator_takes() {
    let found = values(
        r#"<listOfCompartments><compartment id="c" constant="true"/></listOfCompartments>
           <listOfSpecies><species id="s" compartment="c" hasOnlySubstanceUnits="true"
             boundaryCondition="false" constant="false"/></listOfSpecies>
           <listOfParameters><parameter id="p" constant="true"/></listOfParameters>"#,
    );
    assert_eq!(
        found,
        vec![
            ("c".to_string(), Ok(1.0)),
            ("s".to_string(), Ok(0.0)),
            ("p".to_string(), Ok(1.0)),
        ]
    );
}

#[test]
fn a_species_is_the_quantity_a_formula_means() {
    let body = r#"<listOfCompartments><compartment id="c" size="2" constant="true"/></listOfCompartments>
         <listOfSpecies>
           <species id="amount" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true"
             boundaryCondition="false" constant="false"/>
           <species id="concentration" compartment="c" initialAmount="10" hasOnlySubstanceUnits="false"
             boundaryCondition="false" constant="false"/>
           <species id="stated" compartment="c" initialConcentration="4" hasOnlySubstanceUnits="false"
             boundaryCondition="false" constant="false"/>
           <species id="as_amount" compartment="c" initialConcentration="4" hasOnlySubstanceUnits="true"
             boundaryCondition="false" constant="false"/>
         </listOfSpecies>"#;
    let found = values(body);
    assert_eq!(
        found,
        vec![
            ("c".to_string(), Ok(2.0)),
            ("amount".to_string(), Ok(10.0)),
            // the concentration of an amount of 10 in a size of 2
            ("concentration".to_string(), Ok(5.0)),
            ("stated".to_string(), Ok(4.0)),
            // the amount of a concentration of 4 in a size of 2
            ("as_amount".to_string(), Ok(8.0)),
        ]
    );
}

#[test]
fn an_initial_assignment_gives_a_quantity_its_value() {
    let found = values(
        r#"<listOfParameters>
             <parameter id="p" value="1" constant="true"/>
             <parameter id="q" constant="true"/>
           </listOfParameters>
           <listOfInitialAssignments>
             <initialAssignment symbol="q">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><times/><ci>p</ci><cn>4</cn></apply>
               </math>
             </initialAssignment>
           </listOfInitialAssignments>"#,
    );
    assert_eq!(
        found,
        vec![("p".to_string(), Ok(1.0)), ("q".to_string(), Ok(4.0))]
    );
}

#[test]
fn an_initial_assignment_of_an_assigned_quantity_reads_the_rule() {
    let found = values(
        r#"<listOfParameters>
             <parameter id="p" constant="false"/>
             <parameter id="q" constant="true"/>
           </listOfParameters>
           <listOfRules>
             <assignmentRule variable="p">
               <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>7</cn></math>
             </assignmentRule>
           </listOfRules>
           <listOfInitialAssignments>
             <initialAssignment symbol="q">
               <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p</ci></math>
             </initialAssignment>
           </listOfInitialAssignments>"#,
    );
    assert_eq!(
        found,
        vec![("p".to_string(), Ok(7.0)), ("q".to_string(), Ok(7.0))]
    );
}

#[test]
fn a_value_which_needs_itself_is_refused() {
    let found = values(
        r#"<listOfParameters><parameter id="p" constant="true"/></listOfParameters>
           <listOfInitialAssignments>
             <initialAssignment symbol="p">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><plus/><ci>p</ci><cn>1</cn></apply>
               </math>
             </initialAssignment>
           </listOfInitialAssignments>"#,
    );
    assert_eq!(
        found,
        vec![("p".to_string(), Err(EvalError::Cycle("p".to_string())))]
    );
}

#[test]
fn a_symbol_which_is_no_quantity_has_no_value() {
    let text = level3("");
    let document = sbml::read(&text).expect("the document is read");
    let (assignments, rules, rates) = (Vec::new(), Vec::new(), Vec::new());
    let mut start = Start::new(
        &document.model,
        &assignments,
        &rules,
        &rates,
        std::collections::HashMap::new(),
    );
    assert_eq!(
        start.eval(&math("<ci>x</ci>")),
        Err(EvalError::Unknown("x".to_string()))
    );
}
