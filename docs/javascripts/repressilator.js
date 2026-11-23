/* The interactive simulation of the roundtrip page.
 *
 * The repressilator is simulated twice in the browser, with one set of
 * sliders for the parameters of both simulations: the CellML model of the
 * conversion with libopencor and the SBML model it was converted from with
 * sbmlsim-core. Nothing is uploaded and nothing is converted here, the two
 * models are the files of the page. The page loads the two simulators when
 * it opens, so the simulation is the first thing the page shows; a load
 * which fails says so and offers to try again.
 *
 * libopencor reads the CellML document itself and sbmlsim-core compiles the
 * SBML document here, with the compiler of its command line as WebAssembly
 * (`compiler.wasm`): both models of the page are the files the page shows.
 * `scripts/build_simulation.py` writes the compiler, the engine and the math
 * library of the simulator into `simulation/` next to the page, with the
 * versions of the two packages which the JavaScript hosts are loaded for, so
 * the browser runs the simulators of the checks of the repository.
 */

(() => {
  "use strict";

  /** The chart of a plot, the color of a theme and the step of an axis,
   * `chart.js`, which the simulation of the online converter uses as well. */
  const { Chart, niceStep, themeColor } = window.sbml2cellmlChart;

  /** Where the JavaScript hosts of the two simulators are loaded from. */
  const CDN = "https://cdn.jsdelivr.net/npm";

  /** The timecourse of both simulations, the one of the example. */
  const TIMECOURSE = { start: 0, end: 600, steps: 600 };

  /** The tolerances of CVODE, the same for both simulators. */
  const TOLERANCES = { relative: 1e-8, absolute: 1e-12, steps: 100000 };

  /** The parameters of the sliders, with the values of the model. */
  const PARAMETERS = [
    {
      id: "tau_mRNA",
      label: "mRNA half life",
      unit: "min",
      value: 2,
      minimum: 0.5,
      maximum: 10,
      step: 0.1,
    },
    {
      id: "tau_prot",
      label: "protein half life",
      unit: "min",
      value: 10,
      minimum: 2,
      maximum: 30,
      step: 0.5,
    },
    {
      id: "KM",
      label: "repression threshold",
      unit: "molecules/cell",
      value: 40,
      minimum: 5,
      maximum: 100,
      step: 1,
    },
    {
      id: "n",
      label: "Hill coefficient",
      unit: "",
      value: 2,
      minimum: 1,
      maximum: 4,
      step: 0.1,
    },
    {
      id: "eff",
      label: "translation efficiency",
      unit: "proteins/transcript",
      value: 20,
      minimum: 5,
      maximum: 40,
      step: 1,
    },
  ];

  /** The variables both simulations show, the proteins of the example. */
  const PROTEINS = [
    { id: "PX", label: "LacI", color: "#4e79a7" },
    { id: "PY", label: "TetR", color: "#f28e2b" },
    { id: "PZ", label: "cI", color: "#59a14f" },
  ];

  /** The component of the CellML model the conversion writes. */
  const COMPONENT = "sbml";

  /**
   * A wall time as text.
   *
   * @param {number} milliseconds The time in milliseconds.
   * @returns {string} The time with its unit.
   */
  function formatTime(milliseconds) {
    return milliseconds < 10
      ? `${milliseconds.toFixed(1)} ms`
      : `${milliseconds.toFixed(0)} ms`;
  }

  /**
   * Fetch a file of the page as bytes.
   *
   * @param {string} url The URL of the file.
   * @returns {Promise<Uint8Array>} The bytes.
   */
  async function fetchBytes(url) {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`${url} is not available (${response.status})`);
    }
    return new Uint8Array(await response.arrayBuffer());
  }

  /**
   * Fetch a file of the page as text.
   *
   * @param {string} url The URL of the file.
   * @returns {Promise<string>} The text.
   */
  async function fetchText(url) {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`${url} is not available (${response.status})`);
    }
    return await response.text();
  }

  /** The simulation of the CellML model with libopencor. */
  class Cellml {
    /**
     * @param {object} library The module of libopencor.
     * @param {object} document_ The SED document of the model.
     * @param {object} model The model of the document, which takes the changes.
     */
    constructor(library, document_, model) {
      this.library = library;
      this.document = document_;
      this.model = model;
    }

    /**
     * Load libopencor and read the CellML model.
     *
     * @param {string} version The version of libopencor.
     * @param {string} url The URL of the CellML document.
     * @returns {Promise<Cellml>} The simulation.
     */
    static async load(version, url) {
      const module = await import(
        `${CDN}/@opencor/libopencor@${version}/dist/libopencor.js`
      );
      const library = await module.default();
      const file = new library.File(new URL(url, document.baseURI).href);
      file.setContents(new TextEncoder().encode(await fetchText(url)));
      if (file.hasErrors) {
        throw new Error(file.issues.get(0).description);
      }
      const document_ = new library.SedDocument(file);
      const simulation = document_.simulations.get(0);
      simulation.initialTime = TIMECOURSE.start;
      simulation.outputStartTime = TIMECOURSE.start;
      simulation.outputEndTime = TIMECOURSE.end;
      simulation.numberOfSteps = TIMECOURSE.steps;
      const solver = new library.SolverCvode();
      solver.relativeTolerance = TOLERANCES.relative;
      solver.absoluteTolerance = TOLERANCES.absolute;
      solver.maximumNumberOfSteps = TOLERANCES.steps;
      simulation.odeSolver = solver;
      return new Cellml(library, document_, document_.models.get(0));
    }

    /**
     * Simulate the model with the values of the sliders.
     *
     * @param {Array<[string, number]>} changes The value of every parameter.
     * @returns {{time: number[], series: Object<string, number[]>}} The result.
     */
    run(changes) {
      this.model.removeAllChanges();
      for (const [id, value] of changes) {
        this.model.addChange(
          new this.library.SedChangeAttribute(COMPONENT, id, String(value)),
        );
      }
      const instance = this.document.instantiate();
      try {
        if (instance.hasIssues) {
          throw new Error(instance.issues.get(0).description);
        }
        instance.run();
        const task = instance.tasks.get(0);
        const names = [];
        for (let index = 0; index < task.stateCount; index += 1) {
          names.push(task.stateName(index));
        }
        const series = {};
        for (const protein of PROTEINS) {
          // the name of a state is `component/variable`
          const index = names.indexOf(`${COMPONENT}/${protein.id}`);
          if (index < 0) {
            throw new Error(`the model has no variable ${protein.id}`);
          }
          // the arrays are views on the memory of the module, which the
          // instance gives back, so the values are copied out of them
          series[protein.id] = Array.from(task.state(index));
        }
        return { time: Array.from(task.voi), series };
      } finally {
        instance.delete();
      }
    }
  }

  /** The simulation of the SBML model with sbmlsim-core. */
  class Sbml {
    /**
     * @param {object} instance The instance of the compiled model.
     */
    constructor(instance) {
      this.instance = instance;
    }

    /**
     * Load sbmlsim-core, compile the SBML model of the page and instantiate
     * it.
     *
     * The compiler of sbmlsim-core is a WebAssembly module as its engine is,
     * so the page compiles the model it shows instead of carrying one which
     * was compiled for it: what the browser runs is the document of the
     * [roundtrip example](../roundtrip.md), whatever level of SBML it is.
     *
     * @param {string} version The version of sbmlsim-core.
     * @param {Object<string, string>} urls The URLs of the SBML model, the
     *   compiler, the engine and the math library.
     * @returns {Promise<Sbml>} The simulation.
     */
    static async load(version, urls) {
      const [{ createCompiler }, { createRuntime }] = await Promise.all([
        import(`${CDN}/sbmlsim-core@${version}/compile.mjs`),
        import(`${CDN}/sbmlsim-core@${version}/loader.mjs`),
      ]);
      const [compilerWasm, engine, mathlib, sbml] = await Promise.all([
        fetchBytes(urls.compiler),
        fetchBytes(urls.engine),
        fetchBytes(urls.mathlib),
        fetchText(urls.sbml),
      ]);
      const compiler = await createCompiler({ compiler: compilerWasm });
      const { wasm, description } = compiler.compile(sbml);
      const runtime = await createRuntime({ engine, mathlib });
      return new Sbml(await runtime.instantiate(wasm, description));
    }

    /**
     * Simulate the model with the values of the sliders.
     *
     * @param {Array<[string, number]>} changes The value of every parameter.
     * @returns {{time: number[], series: Object<string, number[]>}} The result.
     */
    run(changes) {
      const result = this.instance.simulate({
        contract: "simulation/1",
        start: TIMECOURSE.start,
        end: TIMECOURSE.end,
        output: { uniform: { steps: TIMECOURSE.steps } },
        // the parameters are set before the initial assignments are
        // evaluated, so the constants of the model follow them
        preinit: changes,
        changes: [],
        steady_state: null,
        selections: ["time", ...PROTEINS.map((protein) => protein.id)],
        settings: {
          relative_tolerance: TOLERANCES.relative,
          absolute_tolerance: { scalar: TOLERANCES.absolute },
          maximum_num_steps: TOLERANCES.steps,
          maximum_time_step: 0,
          initial_time_step: 0,
          stiff: true,
          linear_solver: "auto",
          jacobian: "auto",
        },
      });
      // the values are the rows of the table, row major
      const width = result.columns.length;
      const column = (name) => {
        const index = result.columns.indexOf(name);
        return Array.from(
          { length: result.nRows },
          (_, row) => result.values[row * width + index],
        );
      };
      const series = {};
      for (const protein of PROTEINS) {
        series[protein.id] = column(protein.id);
      }
      return { time: column("time"), series };
    }
  }

  /** The interactive simulation of a page. */
  class Simulation {
    /**
     * @param {HTMLElement} root The element of the simulation.
     */
    constructor(root) {
      this.root = root;
      this.urls = {
        cellml: root.dataset.cellml,
        sbml: root.dataset.sbml,
        compiler: root.dataset.compiler,
        engine: root.dataset.engine,
        mathlib: root.dataset.mathlib,
        versions: root.dataset.versions,
      };
      this.status = root.querySelector('[data-role="status"]');
      this.difference = root.querySelector('[data-role="difference"]');
      this.retry = root.querySelector('[data-action="retry"]');
      this.reset = root.querySelector('[data-action="reset"]');
      this.sliders = new Map();
      const labels = { x: "time (min)", y: "proteins per cell" };
      this.charts = {
        cellml: new Chart(root.querySelector('[data-chart="cellml"]'), labels),
        sbml: new Chart(root.querySelector('[data-chart="sbml"]'), labels),
      };
      this.timings = {
        cellml: root.querySelector('[data-role="cellml-timing"]'),
        sbml: root.querySelector('[data-role="sbml-timing"]'),
      };
      this.cellml = null;
      this.sbml = null;
      this.pending = null;
      this.buildSliders();
      this.retry.addEventListener("click", () => this.load());
      this.reset.addEventListener("click", () => this.restore());
      // the canvases follow the palette of the theme
      new MutationObserver(() => {
        for (const chart of Object.values(this.charts)) {
          chart.draw();
        }
      }).observe(document.body, {
        attributes: true,
        attributeFilter: ["data-md-color-scheme"],
      });
    }

    /** Build one slider per parameter of the model. */
    buildSliders() {
      const list = this.root.querySelector('[data-role="sliders"]');
      for (const parameter of PARAMETERS) {
        const item = document.createElement("div");
        item.className = "simulation__slider";
        const label = document.createElement("label");
        label.className = "simulation__label";
        label.setAttribute("for", `simulation-${parameter.id}`);
        label.textContent = `${parameter.id}, ${parameter.label}`;
        const readout = document.createElement("output");
        readout.className = "simulation__value";
        readout.setAttribute("for", `simulation-${parameter.id}`);
        const input = document.createElement("input");
        input.id = `simulation-${parameter.id}`;
        input.type = "range";
        input.min = String(parameter.minimum);
        input.max = String(parameter.maximum);
        input.step = String(parameter.step);
        input.value = String(parameter.value);
        input.disabled = true;
        const show = () => {
          const unit = parameter.unit === "" ? "" : ` ${parameter.unit}`;
          readout.textContent = `${Number(input.value)}${unit}`;
        };
        show();
        input.addEventListener("input", () => {
          show();
          this.schedule();
        });
        const head = document.createElement("div");
        head.className = "simulation__head";
        head.append(label, readout);
        item.append(head, input);
        list.append(item);
        this.sliders.set(parameter.id, {
          input,
          show,
          value: parameter.value,
        });
      }
    }

    /** Set every slider back to the value of the published model. */
    restore() {
      for (const { input, show, value } of this.sliders.values()) {
        input.value = String(value);
        show();
      }
      this.schedule();
    }

    /**
     * Say what the simulation is doing.
     *
     * @param {string} message The message.
     * @param {string} kind `"info"`, `"success"` or `"error"`.
     */
    say(message, kind) {
      this.status.dataset.kind = kind;
      this.status.textContent = message;
    }

    /** Load both simulators and simulate the published model. */
    async load() {
      this.retry.hidden = true;
      this.say("Loading the two simulators, about 11 MB ...", "info");
      try {
        const versions = JSON.parse(await fetchText(this.urls.versions));
        this.cellml = await Cellml.load(versions.libopencor, this.urls.cellml);
        this.sbml = await Sbml.load(versions["sbmlsim-core"], this.urls);
        this.root.querySelector('[data-role="plots"]').hidden = false;
        for (const { input } of this.sliders.values()) {
          input.disabled = false;
        }
        this.reset.disabled = false;
        this.say(
          `libopencor ${versions.libopencor} and sbmlsim-core ` +
            `${versions["sbmlsim-core"]} run in this browser.`,
          "success",
        );
        this.run();
      } catch (err) {
        this.retry.hidden = false;
        this.say(
          `The simulation is not available: ${err.message}. The models of ` +
            "the page can be simulated locally, see the example below.",
          "error",
        );
      }
    }

    /** Simulate again when the sliders have come to rest. */
    schedule() {
      if (this.cellml === null) {
        return;
      }
      if (this.pending !== null) {
        clearTimeout(this.pending);
      }
      this.pending = setTimeout(() => {
        this.pending = null;
        this.run();
      }, 60);
    }

    /** Simulate both models with the values of the sliders and plot them. */
    run() {
      const changes = PARAMETERS.map((parameter) => [
        parameter.id,
        Number(this.sliders.get(parameter.id).input.value),
      ]);
      try {
        const first = performance.now();
        const cellml = this.cellml.run(changes);
        const second = performance.now();
        const sbml = this.sbml.run(changes);
        const third = performance.now();
        let maximum = 0;
        let largest = 0;
        for (const protein of PROTEINS) {
          const left = cellml.series[protein.id];
          const right = sbml.series[protein.id];
          for (let index = 0; index < left.length; index += 1) {
            maximum = Math.max(maximum, left[index], right[index]);
            largest = Math.max(largest, Math.abs(left[index] - right[index]));
          }
        }
        const step = niceStep(maximum === 0 ? 1 : maximum, 4);
        maximum = Math.ceil((maximum === 0 ? 1 : maximum) / step) * step;
        // the two plots share their axis, so the curves are comparable
        const options = { series: PROTEINS, range: TIMECOURSE, maximum };
        this.charts.cellml.show(cellml, options);
        this.charts.sbml.show(sbml, options);
        this.timings.cellml.textContent = formatTime(second - first);
        this.timings.sbml.textContent = formatTime(third - second);
        this.difference.textContent = largest.toExponential(1);
      } catch (err) {
        this.say(`The simulation failed: ${err.message}`, "error");
      }
    }
  }

  /**
   * Start the simulations of the page.
   *
   * A started simulation is marked, since the theme navigates instantly and
   * runs the script of the page again.
   */
  function start() {
    for (const root of document.querySelectorAll("[data-simulation]")) {
      if (root.dataset.started === "true") {
        continue;
      }
      root.dataset.started = "true";
      new Simulation(root).load();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
