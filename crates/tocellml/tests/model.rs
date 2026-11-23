//! The structure of an SBML model as a CellML model.

mod common;

use cellml::{Constant, Node, Operator};
use common::{conversion, equations, level3, units, variables};
use tocellml::model::{COMPONENT, convert};

#[test]
fn a_reaction_gives_the_rate_and_the_differential_equations() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="2" units="litre" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialConcentration="10" substanceUnits="mole"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
             <species id="S2" compartment="cell" initialConcentration="0" substanceUnits="mole"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfParameters>
             <parameter id="k1" value="0.1" units="per_second" constant="true"/>
           </listOfParameters>
           <listOfUnitDefinitions>
             <unitDefinition id="per_second">
               <listOfUnits><unit kind="second" exponent="-1"/></listOfUnits>
             </unitDefinition>
             <unitDefinition id="mole_per_second">
               <listOfUnits>
                 <unit kind="mole"/>
                 <unit kind="second" exponent="-1"/>
               </listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference species="S1" stoichiometry="1" constant="true"/>
               </listOfReactants>
               <listOfProducts>
                 <speciesReference species="S2" stoichiometry="2" constant="true"/>
               </listOfProducts>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML">
                   <apply><times/><ci>k1</ci><ci>S1</ci><ci>cell</ci></apply>
                 </math>
               </kineticLaw>
             </reaction>
           </listOfReactions>"#,
    ));
    assert_eq!(conversion.model.name, "m");
    assert_eq!(conversion.model.components.len(), 1);
    assert_eq!(conversion.model.components[0].name, COMPONENT);
    assert_eq!(
        variables(&conversion),
        [
            "time [second]",
            "cell = 2 [litre]",
            "k1 = 0.1 [per_second]",
            "S1 = 10 [mole_per_litre]",
            "S2 = 0 [mole_per_litre]",
            // every reaction with a kinetic law is a variable of its rate
            "r1 [mole_per_second]",
        ]
    );
    assert_eq!(
        equations(&conversion),
        [
            // the species in concentration are divided by the compartment,
            // the product carries its stoichiometry
            "d1(S1)/d(time) = times(divide(1, cell), minus(r1))",
            "d1(S2)/d(time) = times(divide(1, cell), 2, r1)",
            "r1 = times(k1, S1, cell)",
        ]
    );
}

#[test]
fn a_species_in_amount_is_not_divided_by_its_compartment() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="10"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
             <species id="B" compartment="cell" initialAmount="1"
                      hasOnlySubstanceUnits="true" boundaryCondition="true" constant="false"/>
           </listOfSpecies>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference species="S1" stoichiometry="1" constant="true"/>
               </listOfReactants>
               <listOfProducts>
                 <speciesReference species="B" stoichiometry="1" constant="true"/>
               </listOfProducts>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>
               </kineticLaw>
             </reaction>
           </listOfReactions>"#,
    ));
    // a boundary species is not changed by the reactions
    assert_eq!(
        equations(&conversion),
        ["d1(S1)/d(time) = minus(r1)", "r1 = S1"]
    );
}

#[test]
fn an_initial_value_is_converted_with_the_size_of_the_compartment() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="4" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="8"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
             <species id="S2" compartment="cell" initialConcentration="3"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
             <species id="S3" compartment="cell"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
           </listOfSpecies>"#,
    ));
    // an amount becomes a concentration and a concentration an amount
    assert!(
        variables(&conversion).contains(&"S1 = 2 [mole_per_litre]".to_string()),
        "{:?}",
        variables(&conversion)
    );
    assert!(variables(&conversion).contains(&"S2 = 12 [mole]".to_string()));
    // a species without an initial amount starts at zero
    assert!(variables(&conversion).contains(&"S3 = 0 [mole]".to_string()));
    assert!(
        conversion
            .warnings
            .iter()
            .any(|warning| warning.contains("the initial value of 'S3' is not set, using 0")),
        "{:?}",
        conversion.warnings
    );
}

#[test]
fn an_assignment_rule_is_an_equation_and_its_target_has_no_initial_value() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="1" constant="false"/>
             <parameter id="k" value="2" constant="true"/>
           </listOfParameters>
           <listOfRules>
             <assignmentRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><times/><ci>k</ci><cn>3</cn></apply>
               </math>
             </assignmentRule>
           </listOfRules>"#,
    ));
    assert_eq!(
        variables(&conversion),
        ["x [dimensionless]", "k = 2 [dimensionless]"]
    );
    assert_eq!(equations(&conversion), ["x = times(k, 3)"]);
    // no differential equation and no use of time: the model is algebraic
    assert!(!variables(&conversion).iter().any(|v| v.starts_with("time")));
}

#[test]
fn a_rate_rule_is_a_differential_equation() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="1" units="dimensionless" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <rateRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><minus/><ci>x</ci></apply>
               </math>
             </rateRule>
           </listOfRules>"#,
    ));
    assert_eq!(
        variables(&conversion),
        ["time [second]", "x = 1 [dimensionless]"]
    );
    assert_eq!(equations(&conversion), ["d1(x)/d(time) = minus(x)"]);
}

#[test]
fn a_model_which_uses_time_without_a_differential_equation_integrates_it() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="0" units="second" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <assignmentRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><times/><cn sbml:units="dimensionless">2</cn>
                   <csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol>
                 </apply>
               </math>
             </assignmentRule>
           </listOfRules>"#,
    ));
    assert_eq!(
        variables(&conversion),
        ["time [second]", "time_state = 0 [second]", "x [second]",]
    );
    assert_eq!(
        equations(&conversion),
        ["x = times(2, time)", "d1(time_state)/d(time) = 1"]
    );
}

#[test]
fn the_variable_of_integration_is_renamed_when_an_element_is_called_time() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="time" value="1" units="second" constant="true"/>
             <parameter id="x" value="1" units="dimensionless" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <rateRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><times/><ci>time</ci>
                   <csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol>
                 </apply>
               </math>
             </rateRule>
           </listOfRules>"#,
    ));
    assert!(
        variables(&conversion).contains(&"time_2 [second]".to_string()),
        "{:?}",
        variables(&conversion)
    );
    assert_eq!(
        equations(&conversion),
        ["d1(x)/d(time_2) = times(time, time_2)"]
    );
}

#[test]
fn a_local_parameter_is_a_variable_of_its_reaction() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="1"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference species="S1" stoichiometry="1" constant="true"/>
               </listOfReactants>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML">
                   <apply><times/><ci>k</ci><ci>S1</ci></apply>
                 </math>
                 <listOfLocalParameters>
                   <localParameter id="k" value="0.5"/>
                 </listOfLocalParameters>
               </kineticLaw>
             </reaction>
             <reaction id="r2" reversible="false">
               <listOfProducts>
                 <speciesReference species="S1" stoichiometry="1" constant="true"/>
               </listOfProducts>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
                 <listOfLocalParameters>
                   <localParameter id="k" value="2"/>
                 </listOfLocalParameters>
               </kineticLaw>
             </reaction>
           </listOfReactions>"#,
    ));
    // the local parameters of the two laws are two variables of their own
    assert!(
        variables(&conversion).contains(&"r1_k = 0.5 [dimensionless]".to_string()),
        "{:?}",
        variables(&conversion)
    );
    assert!(variables(&conversion).contains(&"r2_k = 2 [dimensionless]".to_string()));
    assert_eq!(
        equations(&conversion),
        [
            "d1(S1)/d(time) = plus(minus(r1), r2)",
            "r1 = times(r1_k, S1)",
            "r2 = r2_k",
        ]
    );
}

#[test]
fn a_species_reference_with_an_id_is_a_variable_of_its_stoichiometry() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="1"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference id="s" species="S1" stoichiometry="3" constant="true"/>
               </listOfReactants>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>
               </kineticLaw>
             </reaction>
           </listOfReactions>"#,
    ));
    assert!(
        variables(&conversion).contains(&"s = 3 [dimensionless]".to_string()),
        "{:?}",
        variables(&conversion)
    );
    assert_eq!(
        equations(&conversion),
        ["d1(S1)/d(time) = minus(times(s, r1))", "r1 = S1"]
    );
}

#[test]
fn a_species_in_a_changing_compartment_gets_a_variable_of_its_amount() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="2" constant="false"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialConcentration="5"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfRules>
             <rateRule variable="cell">
               <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
             </rateRule>
           </listOfRules>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference species="S1" stoichiometry="1" constant="true"/>
               </listOfReactants>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>
               </kineticLaw>
             </reaction>
           </listOfReactions>"#,
    ));
    // the amount carries the initial value and the reactions, the
    // concentration follows the size of the compartment
    assert!(
        variables(&conversion).contains(&"S1_amount = 10 [mole]".to_string()),
        "{:?}",
        variables(&conversion)
    );
    assert!(variables(&conversion).contains(&"S1 [mole_per_litre]".to_string()));
    assert_eq!(
        equations(&conversion),
        [
            "S1 = divide(S1_amount, cell)",
            "d1(cell)/d(time) = 1",
            "d1(S1_amount)/d(time) = minus(r1)",
            "r1 = S1",
        ]
    );
}

#[test]
fn the_rate_of_a_variable_is_the_right_hand_side_of_its_equation() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="1" constant="false"/>
             <parameter id="y" value="0" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <rateRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><times/><cn>2</cn><ci>x</ci></apply>
               </math>
             </rateRule>
             <assignmentRule variable="y">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply>
                   <csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol>
                   <ci>x</ci>
                 </apply>
               </math>
             </assignmentRule>
           </listOfRules>"#,
    ));
    assert_eq!(
        equations(&conversion),
        ["y = times(2, x)", "d1(x)/d(time) = times(2, x)"]
    );
}

#[test]
fn the_rate_of_a_variable_without_one_is_zero() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="k" value="1" constant="true"/>
             <parameter id="y" value="0" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <rateRule variable="y">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply>
                   <csymbol definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol>
                   <ci>k</ci>
                 </apply>
               </math>
             </rateRule>
           </listOfRules>"#,
    ));
    assert_eq!(equations(&conversion), ["d1(y)/d(time) = 0"]);
}

#[test]
fn the_conversion_factor_of_a_species_converts_the_extent() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="1" conversionFactor="f"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfParameters>
             <parameter id="f" value="2" constant="true"/>
           </listOfParameters>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference species="S1" stoichiometry="1" constant="true"/>
               </listOfReactants>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>
               </kineticLaw>
             </reaction>
           </listOfReactions>"#,
    ));
    assert_eq!(
        equations(&conversion),
        ["d1(S1)/d(time) = times(f, minus(r1))", "r1 = S1"]
    );
}

#[test]
fn a_non_finite_initial_value_becomes_an_equation() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="INF" constant="true"/>
             <parameter id="y" value="-INF" constant="true"/>
             <parameter id="z" value="NaN" constant="true"/>
           </listOfParameters>"#,
    ));
    assert_eq!(
        variables(&conversion),
        [
            "x [dimensionless]",
            "y [dimensionless]",
            "z [dimensionless]",
        ]
    );
    assert_eq!(
        equations(&conversion),
        ["x = Infinity", "y = minus(Infinity)", "z = NotANumber"]
    );
}

#[test]
fn the_variables_carry_their_units_only_when_the_annotation_is_complete() {
    let body = r#"<listOfUnitDefinitions>
             <unitDefinition id="per_min">
               <listOfUnits><unit kind="second" exponent="-1" multiplier="60"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>
           <listOfParameters>
             <parameter id="k1" value="1" units="per_min" constant="true"/>
             <parameter id="k2" value="1" constant="true"/>
           </listOfParameters>"#;
    let incomplete = conversion(&level3(body));
    // `k2` has no units, so no variable carries any
    assert_eq!(
        variables(&incomplete),
        ["k1 = 1 [dimensionless]", "k2 = 1 [dimensionless]"]
    );
    // the unit definitions are converted nevertheless
    assert_eq!(units(&incomplete), ["per_min"]);
    assert!(
        incomplete
            .warnings
            .iter()
            .any(|warning| warning.contains("the unit annotation is incomplete: k2")),
        "{:?}",
        incomplete.warnings
    );
    let complete = conversion(&level3(&body.replace(
        r#"<parameter id="k2" value="1" constant="true"/>"#,
        r#"<parameter id="k2" value="1" units="dimensionless" constant="true"/>"#,
    )));
    assert_eq!(
        variables(&complete),
        ["k1 = 1 [per_min]", "k2 = 1 [dimensionless]"]
    );
}

#[test]
fn a_number_of_a_formula_carries_its_units() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="0" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <assignmentRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <cn sbml:units="litre">2</cn>
               </math>
             </assignmentRule>
           </listOfRules>"#,
    ));
    assert_eq!(equations(&conversion), ["x = 2[litre]"]);
}

#[test]
fn a_rule_without_mathematics_is_ignored() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="1" constant="false"/>
           </listOfParameters>
           <listOfRules><assignmentRule variable="x"/></listOfRules>"#,
    ));
    assert_eq!(variables(&conversion), ["x = 1 [dimensionless]"]);
    assert!(equations(&conversion).is_empty());
    assert!(
        conversion
            .warnings
            .iter()
            .any(|warning| warning.contains("the rule for 'x' has no mathematics")),
        "{:?}",
        conversion.warnings
    );
}

#[test]
fn a_reaction_without_a_kinetic_law_is_not_converted() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="1"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference species="S1" stoichiometry="1" constant="true"/>
               </listOfReactants>
             </reaction>
           </listOfReactions>"#,
    ));
    assert!(equations(&conversion).is_empty());
    assert!(
        conversion
            .warnings
            .iter()
            .any(|warning| warning.contains("the reaction 'r1' has no kinetic law")),
        "{:?}",
        conversion.warnings
    );
}

#[test]
fn an_unset_stoichiometry_of_level_3_is_one_with_a_warning() {
    let conversion = conversion(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="1"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfReactions>
             <reaction id="r1" reversible="false">
               <listOfReactants>
                 <speciesReference species="S1" constant="true"/>
               </listOfReactants>
               <kineticLaw>
                 <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>
               </kineticLaw>
             </reaction>
           </listOfReactions>"#,
    ));
    assert_eq!(
        equations(&conversion),
        ["d1(S1)/d(time) = minus(r1)", "r1 = S1"]
    );
    assert!(
        conversion
            .warnings
            .iter()
            .any(|warning| warning
                .contains("the stoichiometry of 'S1' in the reaction 'r1' is not set")),
        "{:?}",
        conversion.warnings
    );
}

#[test]
fn a_document_of_level_2_is_converted_as_one_of_level_3() {
    let conversion = conversion(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="level2">
    <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialConcentration="1"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="1" units="dimensionless"/></listOfParameters>
    <listOfRules>
      <rateRule variable="S1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><ci>k</ci><ci>S1</ci></apply></apply>
        </math>
      </rateRule>
    </listOfRules>
  </model>
</sbml>"#,
    );
    // the built in units of level 2 are the units of the variables
    assert_eq!(
        variables(&conversion),
        [
            "time [second]",
            "cell = 1 [litre]",
            "k = 1 [dimensionless]",
            "S1 = 1 [mole_per_litre]",
        ]
    );
    assert_eq!(
        equations(&conversion),
        ["d1(S1)/d(time) = minus(times(k, S1))"]
    );
}

#[test]
fn an_initial_assignment_becomes_the_initial_value() {
    let found = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="1" constant="true"/>
             <parameter id="y" constant="true"/>
           </listOfParameters>
           <listOfInitialAssignments>
             <initialAssignment symbol="y">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><times/><ci>x</ci><cn>4</cn></apply>
               </math>
             </initialAssignment>
           </listOfInitialAssignments>"#,
    ));
    assert_eq!(
        variables(&found),
        vec!["x = 1 [dimensionless]", "y = 4 [dimensionless]"]
    );
    assert!(equations(&found).is_empty(), "the value is no equation");
}

#[test]
fn an_initial_assignment_which_cannot_be_evaluated_is_not_converted() {
    let found = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="1" constant="true"/>
           </listOfParameters>
           <listOfInitialAssignments>
             <initialAssignment symbol="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply>
                   <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
                   <ci>x</ci><cn>1</cn>
                 </apply>
               </math>
             </initialAssignment>
           </listOfInitialAssignments>"#,
    ));
    assert_eq!(variables(&found), vec!["x = 1 [dimensionless]"]);
    assert!(
        found
            .warnings
            .iter()
            .any(|warning| warning.contains("the initial assignment of 'x' is not converted")),
        "the warning says so: {:?}",
        found.warnings
    );
}

#[test]
fn a_model_without_an_id_is_named_by_the_caller() {
    let document = sbml::read(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model>
    <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
  </model>
</sbml>"#,
    )
    .expect("the document is read");
    let conversion = convert(&document, "decay").expect("the model is converted");
    assert_eq!(conversion.model.name, "decay");
}

#[test]
fn the_document_of_the_model_is_cellml_2() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="1" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <rateRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><minus/><ci>x</ci></apply>
               </math>
             </rateRule>
           </listOfRules>"#,
    ));
    let xml = conversion.model.to_xml();
    assert!(
        xml.contains(r#"<model xmlns="http://www.cellml.org/cellml/2.0#""#),
        "{xml}"
    );
    assert!(xml.contains(r#"<component name="sbml">"#), "{xml}");
    assert!(
        xml.contains(r#"<variable name="x" units="dimensionless" initial_value="1"/>"#),
        "{xml}"
    );
    assert!(xml.contains("<bvar>"), "{xml}");
    assert!(xml.contains("<diff/>"), "{xml}");
    // the model is read again as the model it was written from
    let read = cellml::read(&xml).expect("the document is read");
    assert_eq!(read.model, conversion.model);
}

#[test]
fn the_equations_use_the_constants_of_mathml() {
    let conversion = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="x" value="0" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <assignmentRule variable="x">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><times/><pi/><exponentiale/></apply>
               </math>
             </assignmentRule>
           </listOfRules>"#,
    ));
    assert_eq!(
        conversion.model.components[0].math[0],
        Node::Apply {
            operator: Operator::Eq,
            arguments: vec![
                Node::Identifier("x".to_string()),
                Node::Apply {
                    operator: Operator::Other("times".to_string()),
                    arguments: vec![
                        Node::Constant(Constant::Pi),
                        Node::Constant(Constant::Exponentiale),
                    ],
                },
            ],
        }
    );
}

#[test]
fn the_conversion_gives_the_sbml_element_of_every_cellml_element() {
    // the metadata of an SBML element is written next to the CellML file
    // and points at the CellML element, so the caller needs the map
    let conversion = conversion(&common::level3(
        r#"
    <listOfUnitDefinitions>
      <unitDefinition id="per_second">
        <listOfUnits><unit kind="second" exponent="-1" scale="0" multiplier="1"/></listOfUnits>
      </unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialConcentration="1"
               hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="1" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants>
          <speciesReference id="ref" species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>local</ci><ci>S1</ci></apply>
          </math>
          <listOfLocalParameters>
            <localParameter id="local" value="2"/>
          </listOfLocalParameters>
        </kineticLaw>
      </reaction>
    </listOfReactions>"#,
    ));
    let origins: Vec<(&str, &str, &str, &str)> = conversion
        .origins
        .iter()
        .map(|origin| {
            (
                origin.name.as_str(),
                origin.kind.name(),
                origin.id.as_str(),
                origin.parameter.as_str(),
            )
        })
        .collect();
    assert_eq!(
        origins,
        vec![
            ("m", "model", "", ""),
            ("cell", "compartment", "cell", ""),
            ("S1", "species", "S1", ""),
            ("k", "parameter", "k", ""),
            ("r1", "reaction", "r1", ""),
            ("r1_local", "local_parameter", "r1", "local"),
            ("ref", "species_reference", "ref", ""),
            ("per_second", "units", "per_second", ""),
        ]
    );
}

#[test]
fn a_not_libcellml_miscompiles_is_written_with_a_warning() {
    // the generator of libcellml 0.7.2 writes the operand of a `not`
    // without parentheses (`!voi > 5.5` for `not(t > 5.5)`), so the
    // document is right and a simulation of it with libopencor is not;
    // the python converter warns about the same formulas
    let found = conversion(&level3(
        r#"<listOfParameters>
             <parameter id="a" value="1" constant="true"/>
             <parameter id="p" value="0" constant="false"/>
             <parameter id="q" value="0" constant="false"/>
           </listOfParameters>
           <listOfRules>
             <assignmentRule variable="p">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><not/><apply><gt/><ci>a</ci><cn>5</cn></apply></apply>
               </math>
             </assignmentRule>
             <assignmentRule variable="q">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <apply><not/><ci>a</ci></apply>
               </math>
             </assignmentRule>
           </listOfRules>"#,
    ));
    let warnings: Vec<&String> = found
        .warnings
        .iter()
        .filter(|warning| warning.contains("'not'"))
        .collect();
    // the `not` of a relation is warned about, the one of a variable
    // (`!constants[0]`) is written correctly
    assert_eq!(warnings.len(), 1, "{:?}", found.warnings);
    assert!(warnings[0].contains("the equation of 'p'"), "{warnings:?}");
    assert!(
        equations(&found).iter().any(|e| e.contains("not(")),
        "{:?}",
        equations(&found)
    );
}
