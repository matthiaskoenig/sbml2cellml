/* The converter of the browser, the WebAssembly module of the rust crates.
 *
 * `docs/converter/sbml2cellml.wasm` is the crate `crates/wasm` built for
 * `wasm32-unknown-unknown`, which reads a CellML document and writes the
 * SBML of it and reads an SBML document of any level and writes the CellML
 * of it. Nothing is uploaded, and the module is fetched once for the page,
 * when the visitor converts or simulates the first model.
 *
 * The interface of the module is the C ABI of `allocate`,
 * `convert_cellml_to_sbml`, `convert_sbml_to_cellml` and `deallocate`; the
 * result is the JSON `{"sbml": "...", "warnings": [...]}`,
 * `{"cellml": "...", "warnings": [...]}` or `{"error": "..."}`, see the
 * documentation of the crate. `window.sbml2cellmlWasm` holds the two calls
 * the online converter (`converter.js`) and the online simulator
 * (`simulator.js`) convert with.
 */

(() => {
  "use strict";

  /** The module, fetched once for every page which converts. */
  let instance = null;

  /**
   * The module of the converter, fetched and instantiated once.
   *
   * @param {string} url The URL of the module.
   * @returns {Promise<WebAssembly.Instance>} The instance.
   */
  async function load(url) {
    if (instance === null) {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`the converter is not available (${response.status})`);
      }
      const module = await WebAssembly.instantiate(
        await response.arrayBuffer(),
        {},
      );
      instance = module.instance;
    }
    return instance;
  }

  /**
   * Write text into a buffer of the module.
   *
   * @param {WebAssembly.Exports} api The exports of the module.
   * @param {string} text The text.
   * @returns {{pointer: number, length: number}} The buffer of its UTF-8.
   */
  function write(api, text) {
    const bytes = new TextEncoder().encode(text);
    const pointer = api.allocate(bytes.length);
    new Uint8Array(api.memory.buffer, pointer, bytes.length).set(bytes);
    return { pointer, length: bytes.length };
  }

  /**
   * Convert a document with the module.
   *
   * @param {WebAssembly.Instance} wasm The instance of the module.
   * @param {string} direction `"cellml2sbml"` or `"sbml2cellml"`.
   * @param {string} text The document.
   * @param {string} name The name of the model, for an SBML model without an id.
   * @returns {{sbml?: string, cellml?: string, warnings?: string[], error?: string}}
   *   The result of the conversion.
   */
  function convert(wasm, direction, text, name) {
    const api = wasm.exports;
    const document_ = write(api, text);
    const model = direction === "sbml2cellml" ? write(api, name) : null;
    const out = api.allocate(8);
    if (model === null) {
      api.convert_cellml_to_sbml(document_.pointer, document_.length, out);
    } else {
      api.convert_sbml_to_cellml(
        document_.pointer,
        document_.length,
        model.pointer,
        model.length,
        out,
      );
    }
    const [pointer, length] = new Uint32Array(api.memory.buffer, out, 2);
    // the bytes are copied out of the memory of the module before it is
    // given back, since another conversion may grow and move that memory
    const json = new TextDecoder().decode(
      new Uint8Array(api.memory.buffer, pointer, length).slice(),
    );
    api.deallocate(document_.pointer, document_.length);
    if (model !== null) {
      api.deallocate(model.pointer, model.length);
    }
    api.deallocate(out, 8);
    api.deallocate(pointer, length);
    return JSON.parse(json);
  }

  window.sbml2cellmlWasm = { load, convert };
})();
