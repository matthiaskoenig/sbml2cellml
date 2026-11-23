/* The online converter of the landing page.
 *
 * The conversion runs in the browser: `docs/converter/sbml2cellml.wasm` is
 * the crate `crates/wasm` built for `wasm32-unknown-unknown`, which reads a
 * CellML document and writes the SBML of it. Nothing is uploaded, and the
 * module is fetched when the visitor converts the first model.
 *
 * The interface of the module is the C ABI of `allocate`,
 * `convert_cellml_to_sbml` and `deallocate`; the result is the JSON
 * `{"sbml": "...", "warnings": [...]}` or `{"error": "..."}`, see the
 * documentation of the crate.
 */

(() => {
  "use strict";

  /** The largest document the page converts, so a wrong file fails early. */
  const MAXIMUM_SIZE = 32 * 1024 * 1024;

  /** The lines of the result the page shows. */
  const PREVIEW_LINES = 400;

  /** The module, fetched once. */
  let instance = null;

  /** The conversion of the file which is shown, for the download. */
  let converted = null;

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
   * Convert a CellML document with the module.
   *
   * @param {WebAssembly.Instance} wasm The instance of the module.
   * @param {string} text The CellML document.
   * @returns {{sbml?: string, warnings?: string[], error?: string}} The result.
   */
  function convert(wasm, text) {
    const api = wasm.exports;
    const document_ = new TextEncoder().encode(text);
    const input = api.allocate(document_.length);
    new Uint8Array(api.memory.buffer, input, document_.length).set(document_);
    const out = api.allocate(8);
    api.convert_cellml_to_sbml(input, document_.length, out);
    const [pointer, length] = new Uint32Array(api.memory.buffer, out, 2);
    // the bytes are copied out of the memory of the module before it is
    // given back, since another conversion may grow and move that memory
    const json = new TextDecoder().decode(
      new Uint8Array(api.memory.buffer, pointer, length).slice(),
    );
    api.deallocate(input, document_.length);
    api.deallocate(out, 8);
    api.deallocate(pointer, length);
    return JSON.parse(json);
  }

  /**
   * The name of the SBML file of a CellML file: the stem with `.xml`.
   *
   * @param {string} name The name of the CellML file.
   * @returns {string} The name of the SBML file.
   */
  function sbmlName(name) {
    const stem = name.replace(/\.(cellml|xml)$/i, "");
    return `${stem || "model"}.xml`;
  }

  /**
   * A size in bytes as text.
   *
   * @param {number} size The size in bytes.
   * @returns {string} The size with its unit.
   */
  function formatSize(size) {
    if (size < 1024) {
      return `${size} B`;
    }
    if (size < 1024 * 1024) {
      return `${(size / 1024).toFixed(0)} KiB`;
    }
    return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
  }

  /** The converter of a page, its elements and what they do. */
  class Converter {
    /**
     * @param {HTMLElement} root The element of the converter.
     */
    constructor(root) {
      this.root = root;
      this.url = root.dataset.module;
      this.example = root.dataset.example;
      this.status = root.querySelector("[data-role=status]");
      this.result = root.querySelector("[data-role=result]");
      this.code = root.querySelector("[data-role=code]");
      this.warnings = root.querySelector("[data-role=warnings]");
      this.warningList = root.querySelector("[data-role=warning-list]");
      this.download = root.querySelector("[data-action=download]");
      this.copy = root.querySelector("[data-action=copy]");
      this.input = root.querySelector("input[type=file]");
      this.drop = root.querySelector("[data-role=drop]");
      this.connect();
    }

    /** Listen to the file input, the drop zone, the example and the buttons. */
    connect() {
      this.input.addEventListener("change", () => {
        const [file] = this.input.files;
        if (file) {
          this.run(file.name, file);
        }
      });
      for (const event of ["dragenter", "dragover"]) {
        this.drop.addEventListener(event, (change) => {
          change.preventDefault();
          this.drop.classList.add("converter__drop--over");
        });
      }
      for (const event of ["dragleave", "drop"]) {
        this.drop.addEventListener(event, () => {
          this.drop.classList.remove("converter__drop--over");
        });
      }
      this.drop.addEventListener("drop", (change) => {
        change.preventDefault();
        const [file] = change.dataTransfer.files;
        if (file) {
          this.run(file.name, file);
        }
      });
      const example = this.root.querySelector("[data-action=example]");
      if (example && this.example) {
        example.addEventListener("click", () => this.runExample());
      }
      this.download.addEventListener("click", () => this.save());
      this.copy.addEventListener("click", () => this.toClipboard());
      for (const tab of this.root.querySelectorAll("[data-direction]")) {
        tab.addEventListener("click", () => this.select(tab.dataset.direction));
      }
    }

    /**
     * Show the panel of a direction.
     *
     * @param {string} direction The direction of the panel.
     */
    select(direction) {
      for (const tab of this.root.querySelectorAll("[data-direction]")) {
        const selected = tab.dataset.direction === direction;
        tab.setAttribute("aria-selected", String(selected));
        tab.classList.toggle("converter__tab--active", selected);
      }
      for (const panel of this.root.querySelectorAll("[data-panel]")) {
        panel.hidden = panel.dataset.panel !== direction;
      }
    }

    /**
     * Say what the converter is doing.
     *
     * @param {string} message The message.
     * @param {string} kind `"info"`, `"error"` or `"success"`.
     */
    say(message, kind = "info") {
      this.status.textContent = message;
      this.status.dataset.kind = kind;
    }

    /** Convert the example model of the documentation. */
    async runExample() {
      this.say("Loading the example model ...");
      try {
        const response = await fetch(this.example);
        if (!response.ok) {
          throw new Error(`the example is not available (${response.status})`);
        }
        await this.run(this.example.split("/").pop(), await response.text());
      } catch (err) {
        this.say(String(err.message || err), "error");
      }
    }

    /**
     * Convert a model and show the result.
     *
     * @param {string} name The name of the file.
     * @param {File|string} source The file or its text.
     */
    async run(name, source) {
      converted = null;
      this.result.hidden = true;
      this.warnings.hidden = true;
      this.download.disabled = true;
      this.copy.disabled = true;
      if (source instanceof File && source.size > MAXIMUM_SIZE) {
        this.say(
          `${name} is ${formatSize(source.size)}, which is larger than the ` +
            `${formatSize(MAXIMUM_SIZE)} the online converter takes: ` +
            `convert it with the python package.`,
          "error",
        );
        return;
      }
      this.say(`Converting ${name} ...`);
      try {
        const text =
          source instanceof File ? await source.text() : String(source);
        const wasm = await load(this.url);
        const start = performance.now();
        const result = convert(wasm, text);
        const seconds = performance.now() - start;
        if (result.error) {
          this.say(`${name} was not converted: ${result.error}`, "error");
          return;
        }
        converted = { name: sbmlName(name), sbml: result.sbml };
        this.show(name, result, seconds);
      } catch (err) {
        this.say(
          `${name} was not converted: ${String(err.message || err)}`,
          "error",
        );
      }
    }

    /**
     * Show the SBML of a conversion and its warnings.
     *
     * @param {string} name The name of the file.
     * @param {{sbml: string, warnings: string[]}} result The conversion.
     * @param {number} seconds The time of the conversion in milliseconds.
     */
    show(name, result, seconds) {
      const lines = result.sbml.split("\n");
      this.code.textContent = lines.slice(0, PREVIEW_LINES).join("\n");
      if (lines.length > PREVIEW_LINES) {
        this.code.textContent += `\n... ${
          lines.length - PREVIEW_LINES
        } more lines, the download has the complete model`;
      }
      this.result.hidden = false;
      this.download.disabled = false;
      this.copy.disabled = false;
      this.download.textContent = `Download ${converted.name}`;
      if (result.warnings.length > 0) {
        this.warningList.textContent = "";
        for (const warning of result.warnings) {
          const item = document.createElement("li");
          item.textContent = warning;
          this.warningList.append(item);
        }
        this.warnings.hidden = false;
        this.warnings.querySelector("summary").textContent =
          result.warnings.length === 1
            ? "1 warning of the conversion"
            : `${result.warnings.length} warnings of the conversion`;
      }
      const size = formatSize(new Blob([result.sbml]).size);
      this.say(
        `${name} was converted to SBML level 3 version 2 in ` +
          `${seconds.toFixed(seconds < 10 ? 1 : 0)} ms, ${size}.`,
        "success",
      );
    }

    /** Save the SBML of the conversion as a file. */
    save() {
      if (converted === null) {
        return;
      }
      const blob = new Blob([converted.sbml], { type: "application/xml" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = converted.name;
      link.click();
      URL.revokeObjectURL(url);
    }

    /** Write the SBML of the conversion to the clipboard. */
    async toClipboard() {
      if (converted === null) {
        return;
      }
      try {
        await navigator.clipboard.writeText(converted.sbml);
        this.copy.textContent = "Copied";
        setTimeout(() => {
          this.copy.textContent = "Copy";
        }, 2000);
      } catch (err) {
        this.say(`The clipboard is not available: ${err.message}`, "error");
      }
    }
  }

  /**
   * Start the converters of the page.
   *
   * A started converter is marked, since the theme navigates instantly and
   * runs the script of the page again.
   */
  function start() {
    for (const root of document.querySelectorAll("[data-converter]")) {
      if (root.dataset.started === "true") {
        continue;
      }
      root.dataset.started = "true";
      new Converter(root);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
