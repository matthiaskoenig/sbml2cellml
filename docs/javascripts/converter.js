/* The online converter of the landing page.
 *
 * Both conversions run in the browser: `docs/converter/sbml2cellml.wasm` is
 * the crate `crates/wasm` built for `wasm32-unknown-unknown`, which reads a
 * CellML document and writes the SBML of it and reads an SBML document of
 * any level and writes the CellML of it. Nothing is uploaded, and the
 * module is fetched when the visitor converts the first model.
 *
 * The interface of the module is the C ABI of `allocate`,
 * `convert_cellml_to_sbml`, `convert_sbml_to_cellml` and `deallocate`; the
 * result is the JSON `{"sbml": "...", "warnings": [...]}`,
 * `{"cellml": "...", "warnings": [...]}` or `{"error": "..."}`, see the
 * documentation of the crate.
 */

(() => {
  "use strict";

  /** The largest document the page converts, so a wrong file fails early. */
  const MAXIMUM_SIZE = 32 * 1024 * 1024;

  /** The lines of the result the page shows. */
  const PREVIEW_LINES = 400;

  /** What a direction of the conversion reads and writes. */
  const DIRECTIONS = {
    cellml2sbml: {
      /** The key of the result in the JSON of the module. */
      key: "sbml",
      /** The suffix of the file of the result. */
      suffix: ".xml",
      /** What the result is, for the status line. */
      result: "SBML level 3 version 2",
    },
    sbml2cellml: {
      key: "cellml",
      suffix: ".cellml",
      result: "CellML 2.0",
    },
  };

  /** The module, fetched once for every direction of the page. */
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

  /**
   * The stem of a file name, without the suffix of a model.
   *
   * @param {string} name The name of the file.
   * @returns {string} The stem, `model` for a name which is only a suffix.
   */
  function stem(name) {
    return name.replace(/\.(cellml|sbml|xml)$/i, "") || "model";
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

  /** The panel of one direction, its elements and what they do. */
  class Panel {
    /**
     * @param {HTMLElement} root The element of the panel.
     * @param {string} url The URL of the module.
     */
    constructor(root, url) {
      this.root = root;
      this.url = url;
      this.direction = root.dataset.panel;
      this.what = DIRECTIONS[this.direction];
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
      /** The conversion which is shown, for the download and the clipboard. */
      this.converted = null;
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
      this.converted = null;
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
        const result = convert(wasm, this.direction, text, stem(name));
        const seconds = performance.now() - start;
        if (result.error) {
          this.say(`${name} was not converted: ${result.error}`, "error");
          return;
        }
        this.converted = {
          name: `${stem(name)}${this.what.suffix}`,
          model: result[this.what.key],
        };
        this.show(name, result.warnings, seconds);
      } catch (err) {
        this.say(
          `${name} was not converted: ${String(err.message || err)}`,
          "error",
        );
      }
    }

    /**
     * Show the model of a conversion and its warnings.
     *
     * @param {string} name The name of the file.
     * @param {string[]} warnings The warnings of the conversion.
     * @param {number} seconds The time of the conversion in milliseconds.
     */
    show(name, warnings, seconds) {
      const lines = this.converted.model.split("\n");
      this.code.textContent = lines.slice(0, PREVIEW_LINES).join("\n");
      if (lines.length > PREVIEW_LINES) {
        this.code.textContent += `\n... ${
          lines.length - PREVIEW_LINES
        } more lines, the download has the complete model`;
      }
      this.result.hidden = false;
      this.download.disabled = false;
      this.copy.disabled = false;
      this.download.textContent = `Download ${this.converted.name}`;
      if (warnings.length > 0) {
        this.warningList.textContent = "";
        for (const warning of warnings) {
          const item = document.createElement("li");
          item.textContent = warning;
          this.warningList.append(item);
        }
        this.warnings.hidden = false;
        this.warnings.querySelector("summary").textContent =
          warnings.length === 1
            ? "1 warning of the conversion"
            : `${warnings.length} warnings of the conversion`;
      }
      const size = formatSize(new Blob([this.converted.model]).size);
      this.say(
        `${name} was converted to ${this.what.result} in ` +
          `${seconds.toFixed(seconds < 10 ? 1 : 0)} ms, ${size}.`,
        "success",
      );
    }

    /** Save the model of the conversion as a file. */
    save() {
      if (this.converted === null) {
        return;
      }
      const blob = new Blob([this.converted.model], {
        type: "application/xml",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = this.converted.name;
      link.click();
      URL.revokeObjectURL(url);
    }

    /** Write the model of the conversion to the clipboard. */
    async toClipboard() {
      if (this.converted === null) {
        return;
      }
      try {
        await navigator.clipboard.writeText(this.converted.model);
        this.copy.textContent = "Copied";
        setTimeout(() => {
          this.copy.textContent = "Copy";
        }, 2000);
      } catch (err) {
        this.say(`The clipboard is not available: ${err.message}`, "error");
      }
    }
  }

  /** The converter of a page: the tabs of the directions and their panels. */
  class Converter {
    /**
     * @param {HTMLElement} root The element of the converter.
     */
    constructor(root) {
      this.root = root;
      for (const panel of root.querySelectorAll("[data-panel]")) {
        new Panel(panel, root.dataset.module);
      }
      for (const tab of root.querySelectorAll("[data-direction]")) {
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
