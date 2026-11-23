//! The writer: a model which is read and written again is the same model.
//!
//! A document of CellML 1.0 or 1.1 moves to CellML 2.0 as it is written, which
//! [`normalize`] does to the model of the document it is compared with: the
//! interfaces, the new base units, the unit definitions of a component and the
//! offset of a unit, which CellML 2.0 has no place for, and the units of a
//! number, which CellML 2.0 requires.

use cellml::{Direction, Document, Interface, Model, Node, read};

/// A fixture of the repository, `tests/data` of the python package.
fn fixture(name: &str) -> String {
    let path = format!("{}/../../tests/data/{name}", env!("CARGO_MANIFEST_DIR"));
    std::fs::read_to_string(&path).unwrap_or_else(|err| panic!("{path}: {err}"))
}

/// An example of the repository, `examples/models`.
fn example(name: &str) -> String {
    let path = format!(
        "{}/../../examples/models/{name}",
        env!("CARGO_MANIFEST_DIR")
    );
    std::fs::read_to_string(&path).unwrap_or_else(|err| panic!("{path}: {err}"))
}

/// The model as CellML 2.0 holds it, which the writer gives of any version.
fn normalize(model: &Model) -> Model {
    let mut model = model.clone();
    // the unit definitions of the components become the ones of the model
    let mut units = Vec::new();
    for definition in model
        .units
        .iter()
        .chain(model.components.iter().flat_map(|c| c.units.iter()))
    {
        if definition.import.is_some()
            || units
                .iter()
                .any(|u: &cellml::Units| u.name == definition.name)
        {
            continue;
        }
        let mut definition = definition.clone();
        // new base units are a definition without a unit of its own
        definition.base_units = false;
        for unit in &mut definition.units {
            unit.offset = 0.0;
        }
        units.push(definition);
    }
    let imported: Vec<cellml::Units> = model
        .units
        .iter()
        .filter(|u| u.import.is_some())
        .cloned()
        .collect();
    model.units = imported.into_iter().chain(units).collect();
    for component in &mut model.components {
        component.units.clear();
        for variable in &mut component.variables {
            variable.interface = match (variable.is_public(), variable.is_private()) {
                (true, true) => Interface::PublicAndPrivate,
                (true, false) => Interface::Public,
                (false, true) => Interface::Private,
                (false, false) => Interface::None,
            };
            variable.public_interface = Direction::None;
            variable.private_interface = Direction::None;
        }
        for math in &mut component.math {
            number_units(math);
        }
        for reset in &mut component.resets {
            for math in [&mut reset.test_value, &mut reset.reset_value]
                .into_iter()
                .flatten()
            {
                number_units(math);
            }
        }
    }
    model
}

/// Every number of the mathematics carries units, which CellML 2.0 requires.
fn number_units(node: &mut Node) {
    match node {
        Node::Number { units, .. } => {
            if units.is_none() {
                *units = Some("dimensionless".to_string());
            }
        }
        Node::Apply { arguments, .. } => arguments.iter_mut().for_each(number_units),
        Node::Piecewise { pieces, otherwise } => {
            for (value, condition) in pieces {
                number_units(value);
                number_units(condition);
            }
            if let Some(otherwise) = otherwise {
                number_units(otherwise);
            }
        }
        Node::Derivative { expression, .. } => number_units(expression),
        Node::Qualifier { value, .. } => number_units(value),
        _ => {}
    }
}

/// Read the document, write it and read it again.
fn round_trip(text: &str) -> (Document, Document) {
    let first = read(text).expect("the fixture is read");
    let xml = first.to_xml();
    let second =
        read(&xml).unwrap_or_else(|error| panic!("the written document is read: {error}\n{xml}"));
    (first, second)
}

/// Assert that the written document holds the same model.
fn same_model(text: &str) {
    let (first, second) = round_trip(text);
    assert_eq!(normalize(&first.model), second.model);
    // the writer is idempotent: the second document is the same text again
    assert_eq!(second.to_xml(), second.model.to_xml());
    assert_eq!(read(&second.to_xml()).unwrap().model, second.model);
}

#[test]
fn writes_a_model_of_cellml_2_0() {
    same_model(&example("test_model.cellml"));
}

#[test]
fn writes_a_model_of_coupled_rates() {
    same_model(&fixture("coupled_rates.cellml"));
}

#[test]
fn writes_a_model_of_cellml_1_0_as_cellml_2_0() {
    let text = fixture("decay_cellml_1_0.cellml");
    let (first, second) = round_trip(&text);
    assert_eq!(first.version, cellml::Version::V1_0);
    assert_eq!(second.version, cellml::Version::V2_0);
    assert_eq!(normalize(&first.model), second.model);
}

#[test]
fn writes_the_imports_of_a_model() {
    let text = fixture("import_parent.cellml");
    let (first, second) = round_trip(&text);
    assert_eq!(normalize(&first.model), second.model);
    assert!(
        second.to_xml().contains("xlink:href"),
        "the import keeps its href"
    );
}

#[test]
fn writes_a_component_with_its_resets() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="c">
        <variable name="x" units="dimensionless" initial_value="1"/>
        <variable name="trigger" units="dimensionless"/>
        <reset variable="x" test_variable="trigger" order="1">
          <test_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>trigger</ci>
                <cn xmlns:cellml="http://www.cellml.org/cellml/2.0#"
                    cellml:units="dimensionless">1</cn></apply>
            </math>
          </test_value>
          <reset_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>x</ci>
                <cn xmlns:cellml="http://www.cellml.org/cellml/2.0#"
                    cellml:units="dimensionless">0</cn></apply>
            </math>
          </reset_value>
        </reset>
      </component>
    </model>"#;
    same_model(text);
    let xml = read(text).unwrap().to_xml();
    assert!(xml.contains("<reset variable=\"x\" test_variable=\"trigger\" order=\"1\">"));
    assert!(xml.contains("<test_value>"));
    assert!(xml.contains("<reset_value>"));
}

#[test]
fn writes_a_piecewise_a_derivative_and_the_qualifiers() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="c">
        <variable name="t" units="second"/>
        <variable name="x" units="dimensionless"/>
        <variable name="y" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
            <piecewise>
              <piece>
                <cn cellml:units="dimensionless">1</cn>
                <apply><gt/><ci>y</ci><cn cellml:units="dimensionless">0</cn></apply>
              </piece>
              <otherwise><cn cellml:units="dimensionless">0</cn></otherwise>
            </piecewise>
          </apply>
          <apply><eq/><ci>y</ci>
            <apply><root/><degree><cn cellml:units="dimensionless">3</cn></degree><ci>x</ci></apply>
          </apply>
        </math>
      </component>
    </model>"#;
    same_model(text);
    let xml = read(text).unwrap().to_xml();
    assert!(xml.contains("<piecewise>") && xml.contains("<otherwise>"));
    assert!(xml.contains("<bvar>"));
    assert!(xml.contains("<degree>"));
}

#[test]
fn writes_a_second_derivative_with_its_degree() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="c">
        <variable name="t" units="second"/>
        <variable name="x" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <apply><diff/>
              <bvar><ci>t</ci><degree><cn cellml:units="dimensionless">2</cn></degree></bvar>
              <ci>x</ci>
            </apply>
            <cn cellml:units="dimensionless">0</cn>
          </apply>
        </math>
      </component>
    </model>"#;
    same_model(text);
    let xml = read(text).unwrap().to_xml();
    assert!(xml.contains("<degree><cn cellml:units=\"dimensionless\">2</cn></degree>"));
}

#[test]
fn writes_the_connections_and_the_encapsulation() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="parent">
        <variable name="x" units="dimensionless" interface="private"/>
      </component>
      <component name="child">
        <variable name="x" units="dimensionless" interface="public"/>
      </component>
      <connection component_1="parent" component_2="child">
        <map_variables variable_1="x" variable_2="x"/>
      </connection>
      <encapsulation>
        <component_ref component="parent">
          <component_ref component="child"/>
        </component_ref>
      </encapsulation>
    </model>"#;
    same_model(text);
    let xml = read(text).unwrap().to_xml();
    assert!(xml.contains("<connection component_1=\"parent\" component_2=\"child\">"));
    assert!(xml.contains("<component_ref component=\"child\"/>"));
    assert!(xml.contains("interface=\"private\""));
}

#[test]
fn writes_the_units_of_a_model() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
      <units name="item"/>
      <units name="mM">
        <unit units="mole" prefix="milli"/>
        <unit units="litre" exponent="-1"/>
      </units>
      <units name="odd">
        <unit units="second" multiplier="60" exponent="2"/>
      </units>
      <component name="c">
        <variable name="x" units="mM" initial_value="1"/>
      </component>
    </model>"#;
    same_model(text);
    let xml = read(text).unwrap().to_xml();
    assert!(xml.contains("<units name=\"item\"/>"), "new base units");
    assert!(xml.contains("<unit units=\"mole\" prefix=\"milli\"/>"));
    assert!(xml.contains("<unit units=\"litre\" exponent=\"-1\"/>"));
    assert!(xml.contains("<unit units=\"second\" exponent=\"2\" multiplier=\"60\"/>"));
}

#[test]
fn the_name_of_a_model_is_escaped() {
    let mut model = read(
        r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
             <component name="c"/>
           </model>"#,
    )
    .unwrap()
    .model;
    model.name = "a & b".to_string();
    let xml = model.to_xml();
    assert!(xml.contains("name=\"a &amp; b\""));
    assert_eq!(read(&xml).unwrap().model.name, "a & b");
}

#[test]
fn a_number_without_units_is_written_as_dimensionless() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/1.0#" name="m">
      <component name="c">
        <variable name="x" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/><ci>x</ci><cn>2.5</cn></apply>
        </math>
      </component>
    </model>"#;
    let xml = read(text).unwrap().to_xml();
    assert!(
        xml.contains("<cn cellml:units=\"dimensionless\">2.5</cn>"),
        "{xml}"
    );
}

#[test]
fn a_number_which_needs_an_exponent_is_written_in_the_e_notation() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="c">
        <variable name="x" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/><ci>x</ci>
            <cn type="e-notation" cellml:units="dimensionless">1.5<sep/>-7</cn></apply>
        </math>
      </component>
    </model>"#;
    same_model(text);
    let xml = read(text).unwrap().to_xml();
    // `1.5e-7` is no number of CellML, the notation of MathML carries the exponent
    assert!(
        xml.contains("<cn type=\"e-notation\" cellml:units=\"dimensionless\">1.5<sep/>-7</cn>"),
        "{xml}"
    );
    assert!(!xml.contains("1.5e-7"), "{xml}");
}

#[test]
fn a_number_which_is_no_number_is_written_as_the_element_of_mathml() {
    let mut document = read(
        r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
             <component name="c"><variable name="x" units="dimensionless"/></component>
           </model>"#,
    )
    .unwrap();
    for (value, element) in [
        (f64::NAN, "<notanumber/>"),
        (f64::INFINITY, "<infinity/>"),
        (f64::NEG_INFINITY, "<apply><minus/><infinity/></apply>"),
    ] {
        document.model.components[0].math = vec![Node::Apply {
            operator: cellml::Operator::Eq,
            arguments: vec![
                Node::Identifier("x".to_string()),
                Node::Number {
                    value,
                    units: Some("dimensionless".to_string()),
                },
            ],
        }];
        let xml = document.model.to_xml();
        // a `<cn>` holds a number, an infinity and a NaN are elements of MathML
        assert!(xml.contains(element), "{element} of {value}:\n{xml}");
        assert!(read(&xml).is_ok(), "{xml}");
    }
}
