//! The algebraic rules of an SBML model as the implicit equations of CellML.

mod common;

use common::{conversion, equations, level3, variables};

/// A model of two parameters and the rules of the body.
fn with_rules(rules: &str) -> String {
    level3(&format!(
        r#"<listOfParameters>
             <parameter id="x" value="3" constant="false"/>
             <parameter id="y" value="2" constant="false"/>
           </listOfParameters>
           <listOfRules>{rules}</listOfRules>"#
    ))
}

/// An algebraic rule of a formula.
fn algebraic(formula: &str) -> String {
    format!(
        r#"<algebraicRule>
             <math xmlns="http://www.w3.org/1998/Math/MathML">{formula}</math>
           </algebraicRule>"#
    )
}

#[test]
fn an_algebraic_rule_becomes_an_implicit_equation() {
    // 0 = x - 2 y, so x is 4 while y is 2
    let formula = r#"<apply><minus/>
         <ci>x</ci>
         <apply><times/><cn>2</cn><ci>y</ci></apply>
       </apply>"#;
    let found = conversion(&with_rules(&algebraic(formula)));
    assert!(
        equations(&found)
            .iter()
            .any(|equation| equation == "0 = minus(x, times(2, y))"),
        "the implicit equation: {:?}",
        equations(&found)
    );
    // the solution at the start is the guess of the solver, and the other
    // variable of the rule states its value as an equation, since
    // libcellml takes every variable with an initial value for an unknown
    assert_eq!(
        variables(&found),
        vec!["x = 4 [dimensionless]", "y [dimensionless]"]
    );
    assert!(
        equations(&found).iter().any(|equation| equation == "y = 2"),
        "the value of the other variable: {:?}",
        equations(&found)
    );
}

#[test]
fn an_algebraic_rule_which_determines_nothing_is_not_converted() {
    let body = r#"<listOfParameters>
           <parameter id="x" value="3" constant="true"/>
         </listOfParameters>
         <listOfRules>%RULE%</listOfRules>"#
        .replace("%RULE%", &algebraic("<ci>x</ci>"));
    let found = conversion(&level3(&body));
    assert!(
        equations(&found).is_empty(),
        "no equation: {:?}",
        equations(&found)
    );
    assert!(
        found
            .warnings
            .iter()
            .any(|warning| warning.contains("determines no variable")),
        "the warning says so: {:?}",
        found.warnings
    );
}

#[test]
fn two_rules_which_share_their_candidates_determine_one_variable_each() {
    // 0 = x + y - 5 and 0 = x - y - 1, which determine x and y together:
    // neither keeps a guess of the solver, since libcellml takes every
    // variable with an initial value in an implicit equation for its unknown
    let sum = r#"<apply><minus/>
         <apply><plus/><ci>x</ci><ci>y</ci></apply>
         <cn>5</cn>
       </apply>"#;
    let difference = r#"<apply><minus/>
         <apply><minus/><ci>x</ci><ci>y</ci></apply>
         <cn>1</cn>
       </apply>"#;
    let found = conversion(&with_rules(&format!(
        "{}{}",
        algebraic(sum),
        algebraic(difference)
    )));
    assert_eq!(
        variables(&found),
        vec!["x [dimensionless]", "y [dimensionless]"]
    );
    assert_eq!(equations(&found).len(), 2, "the two implicit equations");
    assert!(
        found
            .warnings
            .iter()
            .filter(|warning| warning.contains("has no guess of the solver"))
            .count()
            == 2,
        "the warnings say so: {:?}",
        found.warnings
    );
}

#[test]
fn every_rule_of_its_own_variable_keeps_its_guess() {
    // 0 = x - 2 and 0 = y - 3, which determine a variable each
    let rule = |variable: &str, value: &str| {
        algebraic(&format!(
            "<apply><minus/><ci>{variable}</ci><cn>{value}</cn></apply>"
        ))
    };
    let found = conversion(&with_rules(&format!(
        "{}{}",
        rule("x", "2"),
        rule("y", "3")
    )));
    assert_eq!(
        variables(&found),
        vec!["x = 2 [dimensionless]", "y = 3 [dimensionless]"]
    );
    assert_eq!(equations(&found).len(), 2, "the two implicit equations");
}
