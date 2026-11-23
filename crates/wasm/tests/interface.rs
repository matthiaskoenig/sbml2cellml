//! The C ABI of the module, on the host: what the page of the browser does.

/// Convert a CellML document through the interface, as the page does it.
fn through_the_interface(text: &str) -> String {
    let bytes = text.as_bytes();
    unsafe {
        let input = sbml2cellml_wasm::allocate(bytes.len());
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), input, bytes.len());
        let words = 2 * size_of::<usize>();
        let out = sbml2cellml_wasm::allocate(words).cast::<usize>();
        sbml2cellml_wasm::convert_cellml_to_sbml(input, bytes.len(), out);
        let pointer = out.read_unaligned();
        let length = out.add(1).read_unaligned();
        let result = std::str::from_utf8(std::slice::from_raw_parts(pointer as *const u8, length))
            .expect("the result is UTF-8")
            .to_string();
        sbml2cellml_wasm::deallocate(input, bytes.len());
        sbml2cellml_wasm::deallocate(out.cast::<u8>(), words);
        sbml2cellml_wasm::deallocate(pointer as *mut u8, length);
        result
    }
}

const MODEL: &str = r#"<?xml version="1.0"?>
<model xmlns="http://www.cellml.org/cellml/2.0#" name="decay">
  <component name="main">
    <variable name="t" units="second"/>
    <variable name="x" units="dimensionless" initial_value="10"/>
    <variable name="k" units="per_second" initial_value="0.1"/>
    <math xmlns="http://www.w3.org/1998/Math/MathML">
      <apply><eq/>
        <apply><diff/><bvar><ci>t</ci></bvar><ci>x</ci></apply>
        <apply><minus/><apply><times/><ci>k</ci><ci>x</ci></apply></apply>
      </apply>
    </math>
  </component>
  <units name="per_second">
    <unit units="second" exponent="-1"/>
  </units>
</model>"#;

#[test]
fn the_interface_converts_a_document() {
    let json = through_the_interface(MODEL);
    assert!(json.starts_with(r#"{"sbml":"#), "{json}");
    assert!(json.contains("rateRule"), "{json}");
    assert!(json.contains(r#""warnings":[]"#), "{json}");
}

#[test]
fn the_interface_gives_the_error_of_a_document_it_cannot_read() {
    let json = through_the_interface("<nonsense/>");
    assert!(json.starts_with(r#"{"error":"#), "{json}");
    assert!(json.contains("not a CellML model"), "{json}");
}

#[test]
fn a_document_with_an_import_is_refused_with_what_to_do() {
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#"
        xmlns:xlink="http://www.w3.org/1999/xlink" name="parent">
      <import xlink:href="child.cellml">
        <component component_ref="child" name="child"/>
      </import>
    </model>"#;
    let json = through_the_interface(text);
    assert!(json.contains("python package"), "{json}");
}

#[test]
fn the_json_of_a_warning_is_escaped() {
    // a document without the units of a variable is converted with a
    // warning, which carries the name in quotes
    let text = r#"<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">
      <component name="main">
        <variable name="x" units="dimensionless" initial_value="1"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><eq/><ci>x</ci><ci>x</ci></apply>
        </math>
      </component>
    </model>"#;
    let json = through_the_interface(text);
    assert!(!json.contains('\n'), "{json}");
}

/// Convert an SBML document through the interface, as the page does it.
fn to_cellml_through_the_interface(text: &str, name: &str) -> String {
    let bytes = text.as_bytes();
    let name_bytes = name.as_bytes();
    unsafe {
        let input = sbml2cellml_wasm::allocate(bytes.len());
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), input, bytes.len());
        let model = sbml2cellml_wasm::allocate(name_bytes.len());
        std::ptr::copy_nonoverlapping(name_bytes.as_ptr(), model, name_bytes.len());
        let words = 2 * size_of::<usize>();
        let out = sbml2cellml_wasm::allocate(words).cast::<usize>();
        sbml2cellml_wasm::convert_sbml_to_cellml(input, bytes.len(), model, name_bytes.len(), out);
        let pointer = out.read_unaligned();
        let length = out.add(1).read_unaligned();
        let result = std::str::from_utf8(std::slice::from_raw_parts(pointer as *const u8, length))
            .expect("the result is UTF-8")
            .to_string();
        sbml2cellml_wasm::deallocate(input, bytes.len());
        sbml2cellml_wasm::deallocate(model, name_bytes.len());
        sbml2cellml_wasm::deallocate(out.cast::<u8>(), words);
        sbml2cellml_wasm::deallocate(pointer as *mut u8, length);
        result
    }
}

const SBML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="decay">
    <listOfParameters>
      <parameter id="x" value="10" constant="false"/>
      <parameter id="k" value="0.1" constant="true"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><ci>k</ci><ci>x</ci></apply></apply>
        </math>
      </rateRule>
    </listOfRules>
  </model>
</sbml>"#;

#[test]
fn the_interface_converts_an_sbml_document() {
    let json = to_cellml_through_the_interface(SBML, "decay");
    assert!(json.starts_with(r#"{"cellml":"#), "{json}");
    assert!(json.contains("name=\\\"decay\\\""), "{json}");
    assert!(json.contains("<diff/>"), "{json}");
}

#[test]
fn an_sbml_document_without_an_id_takes_the_name_of_the_caller() {
    let json = to_cellml_through_the_interface(
        &SBML.replace(r#"<model id="decay">"#, "<model>"),
        "the_file",
    );
    assert!(json.contains("the_file"), "{json}");
}

#[test]
fn the_interface_gives_the_error_of_an_sbml_document_it_cannot_read() {
    let json = to_cellml_through_the_interface("<nonsense/>", "none");
    assert!(json.starts_with(r#"{"error":"#), "{json}");
}

#[test]
fn an_empty_buffer_is_the_null_pointer() {
    unsafe {
        assert!(sbml2cellml_wasm::allocate(0).is_null());
        // a null pointer or a length of zero is no free
        sbml2cellml_wasm::deallocate(std::ptr::null_mut(), 8);
        sbml2cellml_wasm::deallocate(sbml2cellml_wasm::allocate(4), 0);
    }
}
