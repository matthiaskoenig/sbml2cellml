//! The CellML units of an SBML model: the unit definitions and the units of
//! every element which becomes a variable, as the python converter writes
//! them.

use sbml::read;
use tocellml::{Units, is_annotated};

/// A level 3 version 2 document around the body of its model.
fn level3(body: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="m" substanceUnits="mole" timeUnits="second" extentUnits="mole"
         volumeUnits="litre" areaUnits="metre" lengthUnits="metre">{body}</model>
</sbml>"#
    )
}

/// A level 2 version 4 document around the body of its model.
fn level2(body: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="m">{body}</model>
</sbml>"#
    )
}

/// The units of an SBML document and its model, for the assertions.
fn units_of(text: &str) -> (Units, sbml::Model) {
    let document = read(text).expect("the document is read");
    let units = Units::new(&document.model, document.level);
    (units, document.model)
}

/// The units of a definition of the CellML model as
/// `(reference, prefix, exponent, multiplier)`.
fn attributes(units: &Units, name: &str) -> Vec<(String, String, f64, f64)> {
    units
        .definitions()
        .iter()
        .find(|definition| definition.name == name)
        .unwrap_or_else(|| {
            panic!(
                "the units {name} are defined, not {:?}",
                units
                    .definitions()
                    .iter()
                    .map(|d| d.name.clone())
                    .collect::<Vec<_>>()
            )
        })
        .units
        .iter()
        .map(|unit| {
            (
                unit.units.clone(),
                unit.prefix.clone().unwrap_or_default(),
                unit.exponent,
                unit.multiplier,
            )
        })
        .collect()
}

/// The names of the unit definitions of the CellML model.
fn names(units: &Units) -> Vec<String> {
    units
        .definitions()
        .iter()
        .map(|definition| definition.name.clone())
        .collect()
}

#[test]
fn a_unit_definition_becomes_units_of_the_same_name() {
    let (units, _) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="mmole">
               <listOfUnits><unit kind="mole" scale="-3"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    assert_eq!(names(&units), ["mmole"]);
    assert_eq!(
        attributes(&units, "mmole"),
        [("mole".to_string(), "milli".to_string(), 1.0, 1.0)]
    );
}

#[test]
fn a_multiplier_is_outside_of_the_exponent() {
    // SBML `(60 * second)^-1` is CellML `1/60 * second^-1`
    let (units, _) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="per_min">
               <listOfUnits><unit kind="second" exponent="-1" multiplier="60"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    let [(reference, prefix, exponent, multiplier)] =
        attributes(&units, "per_min").try_into().expect("one unit");
    assert_eq!(
        (reference.as_str(), prefix.as_str(), exponent),
        ("second", "", -1.0)
    );
    assert!((multiplier - 1.0 / 60.0).abs() < 1e-15, "{multiplier}");
}

#[test]
fn a_multiplier_which_is_a_power_of_ten_becomes_the_prefix() {
    // `(1000 gram)^-1` is `kilo gram^-1`: the prefix is inside the exponent
    let (units, _) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="per_kg">
               <listOfUnits><unit kind="gram" exponent="-1" multiplier="1000"/></listOfUnits>
             </unitDefinition>
             <unitDefinition id="mul">
               <listOfUnits><unit kind="litre" scale="-3" multiplier="0.001"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    assert_eq!(
        attributes(&units, "per_kg"),
        [("gram".to_string(), "kilo".to_string(), -1.0, 1.0)]
    );
    assert_eq!(
        attributes(&units, "mul"),
        [("litre".to_string(), "micro".to_string(), 1.0, 1.0)]
    );
}

#[test]
fn a_scale_without_a_prefix_is_written_as_the_power_of_ten() {
    let (units, _) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="odd">
               <listOfUnits><unit kind="mole" scale="5"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    assert_eq!(
        attributes(&units, "odd"),
        [("mole".to_string(), "5".to_string(), 1.0, 1.0)]
    );
}

#[test]
fn item_becomes_new_base_units_and_avogadro_a_number() {
    let (mut units, _) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="count">
               <listOfUnits><unit kind="item"/></listOfUnits>
             </unitDefinition>
             <unitDefinition id="number">
               <listOfUnits><unit kind="avogadro"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    // `item` is new base units, a definition without a unit of its own
    assert!(attributes(&units, "item").is_empty());
    assert_eq!(
        attributes(&units, "count"),
        [("item".to_string(), String::new(), 1.0, 1.0)]
    );
    let [(reference, _, _, multiplier)] =
        attributes(&units, "avogadro").try_into().expect("one unit");
    assert_eq!(reference, "dimensionless");
    assert!((multiplier - 6.022_141_79e23).abs() < 1e8, "{multiplier}");
    assert_eq!(units.name("item").as_deref(), Some("item"));
}

#[test]
fn a_kind_which_cellml_does_not_have_is_left_out_with_a_warning() {
    // `celsius` is a unit kind of SBML level 2 version 1 only
    let (units, _) = units_of(&level2(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="temperature">
               <listOfUnits><unit kind="celsius"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    assert!(attributes(&units, "temperature").is_empty());
    assert_eq!(units.warnings().len(), 1, "{:?}", units.warnings());
    assert!(
        units.warnings()[0].contains("celsius"),
        "{:?}",
        units.warnings()
    );
}

#[test]
fn an_id_which_is_no_name_of_cellml_gets_a_letter() {
    let (units, _) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="_per_min">
               <listOfUnits><unit kind="second" exponent="-1" multiplier="60"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    assert_eq!(names(&units), ["u_per_min"]);
}

#[test]
fn an_id_which_is_a_standard_unit_of_cellml_gets_a_suffix() {
    let (units, _) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="second">
               <listOfUnits><unit kind="second" multiplier="60"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>"#,
    ));
    assert_eq!(names(&units), ["second_2"]);
}

#[test]
fn the_units_of_a_compartment_a_parameter_and_a_species() {
    let (mut units, model) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="per_min">
               <listOfUnits><unit kind="second" exponent="-1" multiplier="60"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>
           <listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" units="litre" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialConcentration="1" substanceUnits="mole"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
             <species id="S2" compartment="cell" initialAmount="1" substanceUnits="mole"
                      hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
           </listOfSpecies>
           <listOfParameters><parameter id="k" value="1" units="per_min" constant="true"/></listOfParameters>"#,
    ));
    assert_eq!(units.time(&model).as_deref(), Some("second"));
    assert_eq!(
        units
            .of_compartment(&model, &model.compartments[0])
            .as_deref(),
        Some("litre")
    );
    assert_eq!(
        units.of_parameter(Some("per_min")).as_deref(),
        Some("per_min")
    );
    // a species in concentration is the substance per the size of its compartment
    assert_eq!(
        units.of_species(&model, &model.species[0]).as_deref(),
        Some("mole_per_litre")
    );
    assert_eq!(
        attributes(&units, "mole_per_litre"),
        [
            ("mole".to_string(), String::new(), 1.0, 1.0),
            ("litre".to_string(), String::new(), -1.0, 1.0),
        ]
    );
    // a species with only substance units is its substance, as is its amount
    assert_eq!(
        units.of_species(&model, &model.species[1]).as_deref(),
        Some("mole")
    );
    assert_eq!(
        units.of_amount(&model, &model.species[0]).as_deref(),
        Some("mole")
    );
    // the rate of a reaction is the extent per time
    assert_eq!(
        units.of_reaction(&model).as_deref(),
        Some("mole_per_second")
    );
}

#[test]
fn a_unit_definition_of_the_model_is_used_for_a_concentration() {
    let (mut units, model) = units_of(&level3(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="mmole">
               <listOfUnits><unit kind="mole" scale="-3"/></listOfUnits>
             </unitDefinition>
             <unitDefinition id="mM">
               <listOfUnits>
                 <unit kind="mole" scale="-3"/>
                 <unit kind="litre" exponent="-1"/>
               </listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>
           <listOfCompartments>
             <compartment id="cell" spatialDimensions="3" size="1" units="litre" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialConcentration="1" substanceUnits="mmole"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
           </listOfSpecies>"#,
    ));
    // the quotient is the definition `mM` of the model, no units are added
    assert_eq!(
        units.of_species(&model, &model.species[0]).as_deref(),
        Some("mM")
    );
    assert_eq!(names(&units), ["mmole", "mM"]);
}

#[test]
fn a_compartment_without_dimensions_makes_a_species_its_substance() {
    let (mut units, model) = units_of(&level3(
        r#"<listOfCompartments>
             <compartment id="point" spatialDimensions="0" size="1" constant="true"/>
           </listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="point" initialConcentration="1" substanceUnits="mole"
                      hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
           </listOfSpecies>"#,
    ));
    assert_eq!(
        units
            .of_compartment(&model, &model.compartments[0])
            .as_deref(),
        Some("dimensionless")
    );
    assert_eq!(
        units.of_species(&model, &model.species[0]).as_deref(),
        Some("mole")
    );
}

#[test]
fn a_compartment_of_level_3_without_dimensions_has_no_units() {
    let (mut units, model) = units_of(&level3(
        r#"<listOfCompartments>
             <compartment id="cell" size="1" constant="true"/>
           </listOfCompartments>"#,
    ));
    assert_eq!(units.of_compartment(&model, &model.compartments[0]), None);
}

#[test]
fn the_built_in_units_of_level_2_are_the_kinds_they_stand_for() {
    let (mut units, model) = units_of(&level2(
        r#"<listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialConcentration="1"/>
           </listOfSpecies>
           <listOfParameters><parameter id="k" value="1" units="dimensionless"/></listOfParameters>"#,
    ));
    assert_eq!(units.time(&model).as_deref(), Some("second"));
    assert_eq!(
        units
            .of_compartment(&model, &model.compartments[0])
            .as_deref(),
        Some("litre")
    );
    assert_eq!(
        units.of_species(&model, &model.species[0]).as_deref(),
        Some("mole_per_litre")
    );
    assert_eq!(
        units.of_parameter(Some("dimensionless")).as_deref(),
        Some("dimensionless")
    );
    // the definitions the reader gives a level 2 model are no units of its own
    assert_eq!(names(&units), ["mole_per_litre"]);
}

#[test]
fn the_area_of_level_2_is_added_as_units() {
    let (mut units, model) = units_of(&level2(
        r#"<listOfCompartments>
             <compartment id="membrane" spatialDimensions="2" size="1"/>
           </listOfCompartments>"#,
    ));
    assert_eq!(
        units
            .of_compartment(&model, &model.compartments[0])
            .as_deref(),
        Some("area")
    );
    assert_eq!(
        attributes(&units, "area"),
        [("metre".to_string(), String::new(), 2.0, 1.0)]
    );
}

#[test]
fn a_model_which_redefines_the_units_of_level_2_states_units() {
    let text = level2(
        r#"<listOfUnitDefinitions>
             <unitDefinition id="substance">
               <listOfUnits><unit kind="mole" scale="-3"/></listOfUnits>
             </unitDefinition>
           </listOfUnitDefinitions>
           <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>"#,
    );
    let (mut units, model) = units_of(&text);
    assert!(is_annotated(&model, 2), "the redefinition is an annotation");
    // the redefinition of the model stands, not the kind it replaces
    assert_eq!(units.name("substance").as_deref(), Some("substance"));
    assert_eq!(
        attributes(&units, "substance"),
        [("mole".to_string(), "milli".to_string(), 1.0, 1.0)]
    );
}

#[test]
fn a_model_states_units_when_an_element_or_the_model_has_them() {
    let (_, bare) = units_of(&level2(
        r#"<listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
           <listOfParameters><parameter id="k" value="1"/></listOfParameters>"#,
    ));
    assert!(
        !is_annotated(&bare, 2),
        "the built in units of level 2 are no annotation"
    );
    let (_, parameter) = units_of(&level2(
        r#"<listOfParameters><parameter id="k" value="1" units="dimensionless"/></listOfParameters>"#,
    ));
    assert!(is_annotated(&parameter, 2));
    let (_, species) = units_of(&level2(
        r#"<listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
           <listOfSpecies>
             <species id="S1" compartment="cell" initialAmount="1" substanceUnits="substance"/>
           </listOfSpecies>"#,
    ));
    assert!(is_annotated(&species, 2));
    let (_, model_units) = units_of(&level3(
        r#"<listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>"#,
    ));
    assert!(is_annotated(&model_units, 3), "the model states its units");
    let (_, nothing) = units_of(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="m">
    <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
  </model>
</sbml>"#,
    );
    assert!(!is_annotated(&nothing, 3), "the model says nothing");
}

#[test]
fn the_units_of_a_number_are_the_reference_when_the_model_does_not_define_it() {
    let (mut units, _) = units_of(&level3(""));
    assert_eq!(units.number_units("mole"), "mole");
    assert_eq!(units.number_units("unknown"), "unknown");
    assert_eq!(units.name("unknown"), None);
}
