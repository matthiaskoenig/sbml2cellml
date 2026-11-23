//! The converter over the CellML fixtures of the repository and over the
//! constructs of a model the conversion has to read: a rate, an
//! assignment, a computed constant, an implicit equation and units.

use convert::analysis::EquationKind;
use convert::{analysis, convert};
use sbml::Math;

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

/// The SBML of a document.
fn xml(text: &str) -> String {
    let document = cellml::read(text).unwrap();
    convert(&document.model).unwrap().document.to_xml()
}

#[test]
fn converts_the_example_model() {
    let xml = xml(&example("test_model.cellml"));
    assert!(xml.contains("<model id=\"test_model\" name=\"test_model\" timeUnits=\"second\">"));
    assert!(
        xml.contains("<parameter id=\"m\" value=\"10\" units=\"kilogram\" constant=\"false\"/>")
    );
    assert!(xml.contains(
        "<parameter id=\"alpha\" value=\"0.05\" units=\"per_second\" constant=\"true\"/>"
    ));
    assert!(xml.contains("<rateRule variable=\"m\">"));
    // the units of the model are expanded to the base units of SBML
    assert!(xml.contains("<unit kind=\"second\" exponent=\"-1\" scale=\"0\" multiplier=\"1\"/>"));
}

/// A model with one equation of every kind the converter writes.
const KINDS: &str = r#"<?xml version="1.0"?>
<model xmlns="http://www.cellml.org/cellml/2.0#"
       xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="kinds">
  <units name="per_second">
    <unit units="second" exponent="-1"/>
  </units>
  <component name="c">
    <variable name="t" units="second"/>
    <variable name="x" units="dimensionless" initial_value="1"/>
    <variable name="k" units="per_second" initial_value="2"/>
    <variable name="doubled" units="per_second"/>
    <variable name="y" units="dimensionless"/>
    <variable name="z" units="dimensionless"/>
    <math xmlns="http://www.w3.org/1998/Math/MathML">
      <apply><eq/>
        <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
        <apply><times/><apply><minus/><ci>k</ci></apply><ci>x</ci></apply>
      </apply>
      <apply><eq/>
        <ci>doubled</ci>
        <apply><times/><cn cellml:units="dimensionless">2</cn><ci>k</ci></apply>
      </apply>
      <apply><eq/>
        <ci>y</ci>
        <apply><plus/><ci>x</ci><cn cellml:units="dimensionless">1</cn></apply>
      </apply>
      <apply><eq/>
        <apply><times/><ci>z</ci><ci>z</ci></apply>
        <ci>y</ci>
      </apply>
    </math>
  </component>
</model>"#;

#[test]
fn the_kind_of_an_equation_is_the_rule_it_becomes() {
    let document = cellml::read(KINDS).unwrap();
    let (ids, analysis) = analysis(&document.model).unwrap();
    let quantity = |name: &str| ids.quantity_of(&document.model, 0, name).unwrap();
    assert_eq!(analysis.voi, Some(quantity("t")));
    assert_eq!(
        analysis.states.iter().copied().collect::<Vec<_>>(),
        [quantity("x")]
    );
    // `k` has a value and no equation, `doubled` is computed from `k`
    assert!(analysis.constants.contains(&quantity("k")));
    assert!(analysis.computed.contains(&quantity("doubled")));
    // `z` is the unknown of the implicit equation `z * z = y`
    assert!(analysis.implicit.contains(&quantity("z")));
    assert_eq!(
        analysis
            .equations
            .iter()
            .map(|equation| equation.kind)
            .collect::<Vec<_>>(),
        [
            EquationKind::Rate {
                state: quantity("x")
            },
            EquationKind::Assignment {
                target: quantity("doubled")
            },
            EquationKind::Assignment {
                target: quantity("y")
            },
            EquationKind::Algebraic,
        ]
    );

    let xml = xml(KINDS);
    assert!(xml.contains("<rateRule variable=\"x\">"));
    assert!(xml.contains("<assignmentRule variable=\"y\">"));
    assert!(xml.contains("<algebraicRule>"));
    assert!(xml.contains("<initialAssignment symbol=\"doubled\">"));
    // the unknown of an implicit equation is no constant, and a computed
    // constant is one
    assert!(xml.contains("<parameter id=\"z\" units=\"dimensionless\" constant=\"false\"/>"));
    assert!(xml.contains("<parameter id=\"doubled\" units=\"per_second\" constant=\"true\"/>"));
    // the residual of `z * z = y` is `z * z - y`
    assert!(xml.contains("<minus/>"));
}

#[test]
fn the_equation_of_a_rule_is_written_as_the_mathematics_of_sbml() {
    let xml = xml(KINDS);
    // a number keeps its units, which SBML writes as `sbml:units`
    assert!(xml.contains("<cn sbml:units=\"dimensionless\"> 2 </cn>"));
    assert!(xml.contains("xmlns:sbml=\"http://www.sbml.org/sbml/level3/version2/core\""));
    // the variable of integration is the time of SBML and no parameter
    assert!(!xml.contains("<parameter id=\"t\""));
}

/// A model of CellML 1.0 whose two components share a variable.
const CONNECTED: &str = r#"<?xml version="1.0"?>
<model xmlns="http://www.cellml.org/cellml/1.0#"
       xmlns:cellml="http://www.cellml.org/cellml/1.0#" name="connected">
  <units name="per_second">
    <unit units="second" exponent="-1"/>
  </units>
  <component name="environment">
    <variable name="time" units="second" public_interface="out"/>
  </component>
  <component name="cell">
    <variable name="time" units="second" public_interface="in"/>
    <variable name="V" units="dimensionless" initial_value="1"/>
    <variable name="k" units="per_second" initial_value="3"/>
    <math xmlns="http://www.w3.org/1998/Math/MathML">
      <apply><eq/>
        <apply><diff/><bvar><ci>time</ci></bvar><ci>V</ci></apply>
        <apply><times/><ci>k</ci><ci>V</ci></apply>
      </apply>
    </math>
  </component>
  <connection>
    <map_components component_1="cell" component_2="environment"/>
    <map_variables variable_1="time" variable_2="time"/>
  </connection>
</model>"#;

#[test]
fn an_equivalence_set_is_one_parameter() {
    let document = cellml::read(CONNECTED).unwrap();
    let conversion = convert(&document.model).unwrap();
    let model = &conversion.document.model;
    // the two variables `time` are one quantity, the variable of
    // integration, so the model has the parameters of `V` and `k` only
    assert_eq!(
        model
            .parameters
            .iter()
            .map(|parameter| parameter.id.as_str())
            .collect::<Vec<_>>(),
        ["V", "k"]
    );
    assert_eq!(model.time_units.as_deref(), Some("second"));
    assert_eq!(conversion.warnings, Vec::<String>::new());
}

#[test]
fn an_imported_component_is_refused() {
    let document = cellml::read(&fixture("import_parent.cellml")).unwrap();
    let error = convert(&document.model).unwrap_err();
    assert!(
        error.to_string().contains("is imported"),
        "{error} does not say that the component is imported"
    );
}

#[test]
fn a_model_without_a_derivative_has_no_time() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="steady">
      <component name="c">
        <variable name="a" units="dimensionless" initial_value="2"/>
        <variable name="b" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/><ci>b</ci><ci>a</ci></apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let conversion = convert(&document.model).unwrap();
    assert_eq!(conversion.document.model.time_units, None);
    // `b` is computed from the constant `a`, so it is an initial
    // assignment and a constant parameter
    assert_eq!(conversion.document.model.initial_assignments.len(), 1);
    assert!(conversion.document.model.rules.is_empty());
}

#[test]
fn an_operator_which_sbml_does_not_have_is_refused() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="partial">
      <component name="c">
        <variable name="x" units="dimensionless"/>
        <variable name="y" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/><ci>y</ci><apply><mean/><ci>x</ci></apply></apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let error = convert(&document.model).unwrap_err();
    assert_eq!(
        error.to_string(),
        "operator 'mean' has no counterpart in SBML"
    );
}

#[test]
fn imported_units_are_refused() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="borrowed">
      <import xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="units.cellml">
        <units name="mM" units_ref="mM"/>
      </import>
      <component name="c">
        <variable name="x" units="mM" initial_value="1"/>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let error = convert(&document.model).unwrap_err();
    assert_eq!(
        error.to_string(),
        "units 'mM' are imported, which the converter does not resolve"
    );
}

#[test]
fn units_the_model_does_not_define_are_refused() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="typo">
      <component name="c">
        <variable name="x" units="dimensionlsee" initial_value="1"/>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let error = convert(&document.model).unwrap_err();
    assert_eq!(
        error.to_string(),
        "units 'dimensionlsee' are neither defined by the model nor units of SBML"
    );
}

#[test]
fn an_equation_which_uses_its_own_variable_is_implicit() {
    // `x = x / 2 + 1` determines `x`, but not by a value SBML can compute
    // from the others: it is an algebraic rule, else SBML reads a circular
    // assignment rule
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="implicit">
      <component name="c">
        <variable name="x" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <ci>x</ci>
            <apply><plus/>
              <apply><divide/><ci>x</ci><cn cellml:units="dimensionless">2</cn></apply>
              <cn cellml:units="dimensionless">1</cn>
            </apply>
          </apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let conversion = convert(&document.model).unwrap();
    let model = &conversion.document.model;
    assert!(matches!(
        model.rules.as_slice(),
        [sbml::Rule::Algebraic { .. }]
    ));
    assert!(!model.parameters[0].constant);
}

#[test]
fn two_equations_which_give_each_other_s_rate_are_refused() {
    // the analyser of libcellml reads such a model as an ode model with
    // no equations at all, cellml/libcellml#1531
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="coupled">
      <units name="per_second"><unit units="second" exponent="-1"/></units>
      <component name="c">
        <variable name="t" units="second"/>
        <variable name="x" units="dimensionless" initial_value="1"/>
        <variable name="y" units="dimensionless" initial_value="2"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
            <apply><plus/>
              <cn cellml:units="per_second">1</cn>
              <apply><diff/><bvar><ci>t</ci></bvar><ci>y</ci></apply>
            </apply>
          </apply>
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>y</ci></apply>
            <apply><minus/>
              <cn cellml:units="per_second">2</cn>
              <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
            </apply>
          </apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let error = convert(&document.model).unwrap_err();
    assert_eq!(
        error.to_string(),
        "the rate of 'x' and the rate of 'y' are given by each other"
    );
}

#[test]
fn the_rate_of_another_state_is_written_as_rate_of() {
    // `d x / d t = d y / d t + 1` is no cycle, SBML writes the rate of
    // `y` as the `rateOf` of level 3 version 2
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="chained">
      <units name="per_second"><unit units="second" exponent="-1"/></units>
      <component name="c">
        <variable name="t" units="second"/>
        <variable name="x" units="dimensionless" initial_value="1"/>
        <variable name="y" units="dimensionless" initial_value="2"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
            <apply><plus/>
              <cn cellml:units="per_second">1</cn>
              <apply><diff/><bvar><ci>t</ci></bvar><ci>y</ci></apply>
            </apply>
          </apply>
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>y</ci></apply>
            <cn cellml:units="per_second">2</cn>
          </apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let xml = convert(&document.model).unwrap().document.to_xml();
    assert!(xml.contains("definitionURL=\"http://www.sbml.org/sbml/symbols/rateOf\""));
    assert!(xml.contains("<rateRule variable=\"x\">"));
    assert!(xml.contains("<rateRule variable=\"y\">"));
}

#[test]
fn an_equation_which_names_a_rate_is_no_second_rate_equation() {
    // `J = d x / d t` next to `d x / d t = f` determines `J`, not the rate
    // of `x` a second time, as the Winslow 1999 model of the Physiome
    // Model Repository writes it
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="named_rate">
      <units name="per_second"><unit units="second" exponent="-1"/></units>
      <component name="c">
        <variable name="t" units="second"/>
        <variable name="x" units="dimensionless" initial_value="1"/>
        <variable name="J" units="per_second"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <ci>J</ci>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
          </apply>
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
            <cn cellml:units="per_second">2</cn>
          </apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let conversion = convert(&document.model).unwrap();
    let model = &conversion.document.model;
    assert!(
        model
            .rules
            .iter()
            .any(|rule| matches!(rule, sbml::Rule::Rate { variable, .. } if variable == "x"))
    );
    assert!(
        model
            .rules
            .iter()
            .any(|rule| matches!(rule, sbml::Rule::Assignment { variable, .. } if variable == "J"))
    );
}

#[test]
fn a_root_of_the_degree_two_is_the_square_root() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="roots">
      <component name="c">
        <variable name="x" units="dimensionless" initial_value="4"/>
        <variable name="y" units="dimensionless"/>
        <variable name="z" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <ci>y</ci>
            <apply><root/><degree><cn cellml:units="dimensionless">2</cn></degree><ci>x</ci></apply>
          </apply>
          <apply><eq/>
            <ci>z</ci>
            <apply><root/><degree><cn cellml:units="dimensionless">3</cn></degree><ci>x</ci></apply>
          </apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let xml = convert(&document.model).unwrap().document.to_xml();
    // the degree two is left out, every other degree is written
    assert_eq!(xml.matches("<degree>").count(), 1);
    assert!(xml.contains("<cn sbml:units=\"dimensionless\"> 3 </cn>"));
}

#[test]
fn a_reset_becomes_an_event() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="growth">
      <component name="c">
        <variable name="t" units="second"/>
        <variable name="m" units="dimensionless" initial_value="1"/>
        <variable name="m_div" units="dimensionless" initial_value="7"/>
        <variable name="count" units="dimensionless" initial_value="0"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>m</ci></apply>
            <cn cellml:units="dimensionless">1</cn>
          </apply>
        </math>
        <reset variable="m" test_variable="m" order="0">
          <test_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>m</ci><ci>m_div</ci></apply>
            </math>
          </test_value>
          <reset_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>m</ci>
                <apply><divide/><ci>m</ci>
                  <cn cellml:units="dimensionless">2</cn></apply></apply>
            </math>
          </reset_value>
        </reset>
        <reset variable="count" test_variable="m" order="1">
          <test_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>m</ci><ci>m_div</ci></apply>
            </math>
          </test_value>
          <reset_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>count</ci>
                <apply><plus/><ci>count</ci>
                  <cn cellml:units="dimensionless">1</cn></apply></apply>
            </math>
          </reset_value>
        </reset>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let conversion = convert::convert(&document.model).unwrap();
    let events = &conversion.document.model.events;
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].id, "reset_1");
    assert_eq!(events[1].id, "reset_2");
    // the trigger is the equality of the test variable and the test value,
    // the priority the negated order
    assert_eq!(
        events[0].trigger.math,
        Math::apply("eq", vec![Math::identifier("m"), Math::identifier("m_div")])
    );
    assert_eq!(
        events[1].priority,
        Some(Math::Number {
            value: -1.0,
            units: None
        })
    );
    assert_eq!(events[0].assignments[0].variable, "m");
    // `count` is written by a reset only, so it is no constant
    let count = conversion
        .document
        .model
        .parameters
        .iter()
        .find(|parameter| parameter.id == "count")
        .unwrap();
    assert!(!count.constant);
    let xml = conversion.document.to_xml();
    assert!(xml.contains("<event id=\"reset_1\" useValuesFromTriggerTime=\"true\">"));
}

#[test]
fn a_reset_of_a_trigger_variable_gives_the_event_the_condition() {
    // the CellML of an SBML event, as `sbml2cellml` writes it: the trigger
    // is the variable `piecewise(1, condition, 0)` and the reset fires when
    // it reaches 1
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/2.0#" name="pulse">
      <component name="c">
        <variable name="t" units="second"/>
        <variable name="x" units="dimensionless" initial_value="1"/>
        <variable name="trigger" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
            <cn cellml:units="dimensionless">1</cn>
          </apply>
          <apply><eq/>
            <ci>trigger</ci>
            <piecewise>
              <piece>
                <cn cellml:units="dimensionless">1</cn>
                <apply><geq/><ci>t</ci><cn cellml:units="second">5</cn></apply>
              </piece>
              <otherwise><cn cellml:units="dimensionless">0</cn></otherwise>
            </piecewise>
          </apply>
        </math>
        <reset variable="x" test_variable="trigger" order="0">
          <test_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>trigger</ci>
                <cn cellml:units="dimensionless">1</cn></apply>
            </math>
          </test_value>
          <reset_value>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><eq/><ci>x</ci>
                <cn cellml:units="dimensionless">10</cn></apply>
            </math>
          </reset_value>
        </reset>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let conversion = convert::convert(&document.model).unwrap();
    let trigger = &conversion.document.model.events[0].trigger.math;
    assert_eq!(
        trigger,
        &Math::apply(
            "geq",
            vec![
                Math::Time,
                Math::Number {
                    value: 5.0,
                    units: Some("second".to_string())
                }
            ]
        )
    );
}

#[test]
fn the_representative_of_a_set_is_the_variable_its_equation_computes() {
    // `Istim` of the component which computes it, not `J_stim` of the one
    // which uses it, as the analyser of libcellml picks it
    let text = r#"<model xmlns="http://www.cellml.org/cellml/1.0#"
                         xmlns:cellml="http://www.cellml.org/cellml/1.0#" name="stimulus">
      <component name="membrane">
        <variable name="t" units="second" public_interface="in"/>
        <variable name="V" units="dimensionless" initial_value="0"/>
        <variable name="J_stim" units="dimensionless" public_interface="in"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <apply><diff/><bvar><ci>t</ci></bvar><ci>V</ci></apply>
            <ci>J_stim</ci>
          </apply>
        </math>
      </component>
      <component name="stimulus_protocol">
        <variable name="Istim" units="dimensionless" public_interface="out"/>
        <variable name="amplitude" units="dimensionless" initial_value="2"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/><ci>Istim</ci><ci>amplitude</ci></apply>
        </math>
      </component>
      <component name="environment">
        <variable name="t" units="second" public_interface="out"/>
      </component>
      <connection>
        <map_components component_1="membrane" component_2="stimulus_protocol"/>
        <map_variables variable_1="J_stim" variable_2="Istim"/>
      </connection>
      <connection>
        <map_components component_1="membrane" component_2="environment"/>
        <map_variables variable_1="t" variable_2="t"/>
      </connection>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let conversion = convert::convert(&document.model).unwrap();
    let ids: Vec<&str> = conversion
        .document
        .model
        .parameters
        .iter()
        .map(|parameter| parameter.id.as_str())
        .collect();
    assert!(ids.contains(&"Istim"), "{ids:?}");
    assert!(!ids.contains(&"J_stim"), "{ids:?}");
}

#[test]
fn an_n_ary_operator_of_one_argument_is_written_as_its_argument() {
    // MathML allows `plus` with a single argument, which is the argument
    let text = r#"<?xml version="1.0"?>
    <model xmlns="http://www.cellml.org/cellml/2.0#" name="single">
      <component name="main">
        <variable name="x" units="dimensionless" initial_value="2"/>
        <variable name="y" units="dimensionless"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/>
            <ci>y</ci>
            <apply><plus/>
              <apply><plus/><ci>x</ci></apply>
              <cn cellml:units="dimensionless" xmlns:cellml="http://www.cellml.org/cellml/2.0#">1</cn>
            </apply>
          </apply>
        </math>
      </component>
    </model>"#;
    let document = cellml::read(text).unwrap();
    let conversion = convert::convert(&document.model).unwrap();
    let xml = conversion.document.to_xml();
    // the single argument of the inner `plus` is written in its place, so
    // the sum of the formula is the only operator left
    assert_eq!(xml.matches("<plus/>").count(), 1, "{xml}");
}
