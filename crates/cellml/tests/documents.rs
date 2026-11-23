//! The reader over the CellML fixtures of the repository and over the
//! constructs of CellML 1.0 and 1.1 the Physiome models are written with.

use cellml::{Direction, Interface, Node, Operator, ReadError, Version, equivalence_sets, read};

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

#[test]
fn reads_a_cellml_2_document() {
    let document = read(&fixture("import_child.cellml")).unwrap();
    assert_eq!(document.version, Version::V2_0);
    let model = &document.model;
    assert_eq!(model.name, "child");
    assert_eq!(model.units.len(), 1);
    assert_eq!(model.units[0].name, "per_second");
    assert_eq!(model.units[0].units[0].units, "second");
    assert_eq!(model.units[0].units[0].exponent, -1.0);
    assert_eq!(model.components.len(), 1);
    let component = &model.components[0];
    assert_eq!(component.name, "decay");
    let names: Vec<&str> = component
        .variables
        .iter()
        .map(|variable| variable.name.as_str())
        .collect();
    assert_eq!(names, ["t", "m", "k"]);
    assert_eq!(component.variables[1].units, "dimensionless");
    assert_eq!(component.variables[1].initial_value.as_deref(), Some("10"));
    assert_eq!(component.variables[1].interface, Interface::Public);
    assert!(component.variables[1].is_public());
    assert!(!component.variables[2].is_public());
    assert_eq!(component.math.len(), 1);
}

#[test]
fn reads_the_mathematics_of_a_component() {
    let document = read(&example("test_model.cellml")).unwrap();
    let equation = &document.model.components[0].math[0];
    let Node::Apply {
        operator,
        arguments,
    } = equation
    else {
        panic!("the equation is no apply: {equation:?}");
    };
    assert_eq!(*operator, Operator::Eq);
    assert_eq!(arguments.len(), 2);
    let Node::Derivative {
        variable,
        degree,
        expression,
    } = &arguments[0]
    else {
        panic!("the left hand side is no derivative: {:?}", arguments[0]);
    };
    assert_eq!(variable, "t");
    assert_eq!(*degree, 1);
    assert_eq!(**expression, Node::Identifier("m".to_string()));
}

#[test]
fn reads_a_cellml_1_0_document_as_a_cellml_2_one() {
    let document = read(&fixture("decay_cellml_1_0.cellml")).unwrap();
    assert_eq!(document.version, Version::V1_0);
    let component = &document.model.components[0];
    assert_eq!(component.name, "main");
    assert_eq!(component.variables[1].name, "k");
    assert_eq!(component.variables[1].initial_value.as_deref(), Some("0.1"));
    assert_eq!(component.math.len(), 1);
}

#[test]
fn reads_the_imports_of_a_document() {
    let document = read(&fixture("import_parent.cellml")).unwrap();
    assert_eq!(document.model.imports.len(), 1);
    let import = &document.model.imports[0];
    assert_eq!(import.href, "import_child.cellml");
    assert_eq!(import.components.len(), 1);
    assert_eq!(import.components[0].name, "decay_import");
    assert_eq!(import.components[0].reference, "decay");
    // an imported component is a component of the model without a content
    // until the import is resolved, as libcellml reads it
    let component = &document.model.components[0];
    assert_eq!(component.name, "decay_import");
    assert_eq!(
        component.import,
        Some(cellml::ImportRef {
            import: 0,
            reference: "decay".to_string(),
        })
    );
    assert!(component.variables.is_empty());
    assert!(component.math.is_empty());
}

/// A model of CellML 1.0 with two connected components and an
/// encapsulation group, as the models of the Physiome repository are
/// written.
const GROUPED: &str = r#"<?xml version="1.0"?>
<model xmlns="http://www.cellml.org/cellml/1.0#"
       xmlns:cellml="http://www.cellml.org/cellml/1.0#" name="grouped">
  <component name="environment">
    <variable name="time" units="second" public_interface="out"/>
  </component>
  <component name="cell">
    <variable name="time" units="second" public_interface="in"/>
    <variable name="V" units="volt" private_interface="out"/>
  </component>
  <component name="channel">
    <variable name="V" units="volt" public_interface="in"/>
  </component>
  <connection>
    <map_components component_1="cell" component_2="environment"/>
    <map_variables variable_1="time" variable_2="time"/>
  </connection>
  <connection>
    <map_components component_1="cell" component_2="channel"/>
    <map_variables variable_1="V" variable_2="V"/>
  </connection>
  <group>
    <relationship_ref relationship="encapsulation"/>
    <component_ref component="cell">
      <component_ref component="channel"/>
    </component_ref>
  </group>
</model>"#;

#[test]
fn reads_the_connections_and_the_group_of_a_1_0_model() {
    let document = read(GROUPED).unwrap();
    let model = &document.model;
    assert_eq!(model.connections.len(), 2);
    assert_eq!(model.connections[0].component_1, "cell");
    assert_eq!(model.connections[0].component_2, "environment");
    assert_eq!(
        model.connections[0].variables,
        [("time".to_string(), "time".to_string())]
    );
    assert_eq!(
        model.encapsulation_parents(),
        [("channel".to_string(), "cell".to_string())]
    );
    assert_eq!(
        model.components[0].variables[0].public_interface,
        Direction::Out
    );
    assert!(model.components[1].variables[1].is_private());
}

#[test]
fn the_equivalence_sets_are_the_connected_variables() {
    let document = read(GROUPED).unwrap();
    let model = &document.model;
    let names: Vec<Vec<String>> = equivalence_sets(model)
        .iter()
        .map(|set| {
            set.iter()
                .map(|reference| {
                    let component = &model.components[reference.component];
                    format!(
                        "{}/{}",
                        component.name, component.variables[reference.variable].name
                    )
                })
                .collect()
        })
        .collect();
    assert_eq!(
        names,
        [
            vec!["environment/time".to_string(), "cell/time".to_string()],
            vec!["cell/V".to_string(), "channel/V".to_string()],
        ]
    );
}

#[test]
fn reads_a_piecewise_and_a_number_in_e_notation() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="c">
        <variable name="x" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML"
              xmlns:cellml="http://www.cellml.org/cellml/2.0#">
          <apply><eq/><ci>x</ci>
            <piecewise>
              <piece>
                <cn cellml:units="dimensionless" type="e-notation">1.5<sep/>3</cn>
                <apply><lt/><ci>x</ci><cn cellml:units="dimensionless">0</cn></apply>
              </piece>
              <otherwise><cn cellml:units="dimensionless">2</cn></otherwise>
            </piecewise>
          </apply>
        </math>
      </component>
    </model>"#;
    let document = read(text).unwrap();
    let Node::Apply { arguments, .. } = &document.model.components[0].math[0] else {
        panic!("no apply");
    };
    let Node::Piecewise { pieces, otherwise } = &arguments[1] else {
        panic!("no piecewise: {:?}", arguments[1]);
    };
    assert_eq!(pieces.len(), 1);
    assert_eq!(
        pieces[0].0,
        Node::Number {
            value: 1500.0,
            units: Some("dimensionless".to_string()),
        }
    );
    let Node::Apply { operator, .. } = &pieces[0].1 else {
        panic!("no condition");
    };
    assert_eq!(*operator, Operator::Other("lt".to_string()));
    assert!(otherwise.is_some());
}

#[test]
fn a_document_which_is_no_cellml_model_is_refused() {
    let error =
        read("<sbml xmlns=\"http://www.sbml.org/sbml/level3/version2/core\"/>").unwrap_err();
    assert!(matches!(error, ReadError::NotCellML { .. }), "{error:?}");
    let error = read("not xml").unwrap_err();
    assert!(matches!(error, ReadError::Xml(_)), "{error:?}");
}

#[test]
fn a_variable_without_units_is_refused() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="c"><variable name="x"/></component>
    </model>"#;
    let error = read(text).unwrap_err();
    assert_eq!(
        error,
        ReadError::MissingAttribute {
            element: "variable".to_string(),
            attribute: "units".to_string(),
        }
    );
}
