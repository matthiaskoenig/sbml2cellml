//! The events of an SBML model as the resets of a CellML model.

mod common;

use common::{conversion, equations, level3, text, variables};
use tocellml::model::Conversion;

/// The document of a model with one parameter and the events of the body.
fn with_events(events: &str) -> String {
    level3(&format!(
        r#"<listOfParameters>
             <parameter id="p" value="1" constant="false"/>
             <parameter id="q" value="2" constant="false"/>
           </listOfParameters>
           <listOfEvents>{events}</listOfEvents>"#
    ))
}

/// An event of a trigger and one assignment.
fn event(id: &str, trigger: &str, variable: &str, value: &str) -> String {
    full(id, trigger, "", variable, value)
}

/// An event with the elements between its trigger and its assignments, the
/// delay and the priority, in the order of the document.
fn full(id: &str, trigger: &str, between: &str, variable: &str, value: &str) -> String {
    format!(
        r#"<event id="{id}" useValuesFromTriggerTime="true">
             <trigger initialValue="true" persistent="true">
               <math xmlns="http://www.w3.org/1998/Math/MathML">{trigger}</math>
             </trigger>
             {between}
             <listOfEventAssignments>
               <eventAssignment variable="{variable}">
                 <math xmlns="http://www.w3.org/1998/Math/MathML">{value}</math>
               </eventAssignment>
             </listOfEventAssignments>
           </event>"#
    )
}

/// A `<priority>` of a number.
fn priority(value: &str) -> String {
    format!(
        r#"<priority>
             <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>{value}</cn></math>
           </priority>"#
    )
}

/// The condition `time > 5`.
const AFTER_FIVE: &str = r#"<apply><gt/>
     <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
     <cn>5</cn>
   </apply>"#;

/// The resets of the component as `order: variable = value when test`.
fn resets(conversion: &Conversion) -> Vec<String> {
    conversion.model.components[0]
        .resets
        .iter()
        .map(|reset| {
            let value = reset.reset_value.as_ref().map(text).unwrap_or_default();
            let test = reset.test_value.as_ref().map(text).unwrap_or_default();
            format!(
                "{}: {value} when {test} [{}]",
                reset.order, reset.test_variable
            )
        })
        .collect()
}

#[test]
fn an_event_becomes_a_trigger_variable_and_a_reset() {
    let found = conversion(&with_events(&event("e", AFTER_FIVE, "p", "<cn>5</cn>")));
    assert!(
        variables(&found).contains(&"e_trigger [dimensionless]".to_string()),
        "the variable of the trigger: {:?}",
        variables(&found)
    );
    assert!(
        equations(&found)
            .iter()
            .any(|equation| equation == "e_trigger = piecewise(1 if gt(time, 5), else 0)"),
        "the equation of the trigger: {:?}",
        equations(&found)
    );
    assert_eq!(
        resets(&found),
        vec!["0: p = 5 when e_trigger = 1 [e_trigger]"]
    );
}

#[test]
fn the_resets_are_ordered_by_the_priority_of_their_event() {
    let events = format!(
        "{}{}",
        full("low", "<true/>", &priority("1"), "p", "<cn>1</cn>"),
        full("high", "<true/>", &priority("9"), "q", "<cn>2</cn>"),
    );
    let found = conversion(&with_events(&events));
    // SBML fires the event of the highest priority first, CellML applies
    // the reset of the lowest order
    assert_eq!(
        resets(&found),
        vec![
            "0: q = 2 when high_trigger = 1 [high_trigger]",
            "1: p = 1 when low_trigger = 1 [low_trigger]",
        ]
    );
}

#[test]
fn an_event_with_a_delay_becomes_a_reset_which_fires_at_the_trigger() {
    // the delay has no counterpart in CellML: the reset fires when the
    // trigger holds and the metadata of the conversion keeps the delay,
    // which the conversion back to SBML gives the event again
    let delay =
        r#"<delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay>"#;
    let events = full("e", "<true/>", delay, "p", "<cn>5</cn>");
    let found = conversion(&with_events(&events));
    assert_eq!(
        resets(&found),
        vec!["0: p = 5 when e_trigger = 1 [e_trigger]"]
    );
    assert!(
        found
            .warnings
            .iter()
            .any(|warning| warning.contains("has a delay")),
        "the warning says so: {:?}",
        found.warnings
    );
}

#[test]
fn a_delay_without_mathematics_is_ignored() {
    // case 01241 of the SBML test suite: "if an Event Delay with no MathML
    // is encountered, the Delay is ignored"
    let events = full("e", "<true/>", "<delay/>", "p", "<cn>5</cn>");
    let found = conversion(&with_events(&events));
    assert_eq!(
        resets(&found),
        vec!["0: p = 5 when e_trigger = 1 [e_trigger]"]
    );
}

#[test]
fn an_event_without_an_assignment_is_not_converted() {
    let events = r#"<event id="e" useValuesFromTriggerTime="true">
         <trigger initialValue="true" persistent="true">
           <math xmlns="http://www.w3.org/1998/Math/MathML"><true/></math>
         </trigger>
       </event>"#;
    let found = conversion(&with_events(events));
    assert!(resets(&found).is_empty());
    assert!(
        found
            .warnings
            .iter()
            .any(|warning| warning.contains("assigns nothing")),
        "the warning says so: {:?}",
        found.warnings
    );
}

#[test]
fn an_event_without_a_trigger_is_not_converted() {
    let events = r#"<event id="e" useValuesFromTriggerTime="true">
         <listOfEventAssignments>
           <eventAssignment variable="p">
             <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math>
           </eventAssignment>
         </listOfEventAssignments>
       </event>"#;
    let found = conversion(&with_events(events));
    assert!(resets(&found).is_empty());
    assert!(
        found
            .warnings
            .iter()
            .any(|warning| warning.contains("has no trigger")),
        "the warning says so: {:?}",
        found.warnings
    );
}

#[test]
fn an_event_of_mathematics_without_a_counterpart_is_not_converted() {
    let factorial = "<apply><factorial/><cn>3</cn></apply>";
    let found = conversion(&with_events(&event("e", "<true/>", "p", factorial)));
    assert!(resets(&found).is_empty());
    assert!(
        found
            .warnings
            .iter()
            .any(|warning| warning.contains("'factorial', which has no counterpart")),
        "the warning says so: {:?}",
        found.warnings
    );
}

#[test]
fn an_event_which_assigns_what_is_no_variable_is_not_converted() {
    let found = conversion(&with_events(&event(
        "e",
        "<true/>",
        "nothing",
        "<cn>5</cn>",
    )));
    assert!(resets(&found).is_empty());
    assert!(
        found
            .warnings
            .iter()
            .any(|warning| warning.contains("which is no variable of the model")),
        "the warning says so: {:?}",
        found.warnings
    );
}

#[test]
fn an_event_which_assigns_a_species_of_an_amount_sets_the_amount() {
    let body = format!(
        r#"<listOfCompartments>
             <compartment id="c" spatialDimensions="3" size="2" units="litre" constant="false"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="c" initialConcentration="1" substanceUnits="mole"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfRules>
             <rateRule variable="c">
               <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
             </rateRule>
           </listOfRules>
           <listOfEvents>{}</listOfEvents>"#,
        event("e", "<true/>", "S1", "<cn>5</cn>")
    );
    let found = conversion(&level3(&body));
    // the amount is the state of the CellML model, the concentration of the
    // assignment is multiplied with the size of the compartment
    assert_eq!(
        resets(&found),
        vec!["0: S1_amount = times(5, c) when e_trigger = 1 [e_trigger]"]
    );
}

#[test]
fn a_trigger_which_a_reset_cannot_express_is_warned_about() {
    let events = event("e", "<true/>", "p", "<cn>5</cn>").replace(
        "initialValue=\"true\" persistent=\"true\"",
        "initialValue=\"false\" persistent=\"false\"",
    );
    let found = conversion(&with_events(&events));
    assert_eq!(resets(&found).len(), 1, "the event is converted");
    let warnings = found.warnings.join(" ");
    assert!(warnings.contains("initial value 'false'"), "{warnings}");
    assert!(warnings.contains("not persistent"), "{warnings}");
}
