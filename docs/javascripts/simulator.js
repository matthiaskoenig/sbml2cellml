/* The online simulator of the landing page.
 *
 * A published model of the selection is simulated twice in the browser,
 * with one set of sliders for the parameters of both simulations: the
 * CellML side with libopencor and the SBML side with sbmlsim-core, which
 * compiles the SBML document here. One of the two documents is the
 * published model and the other one is the conversion of it, which the
 * WebAssembly module of the rust converters writes in the page
 * (`wasm.js`): a model of BioModels is an SBML model and becomes CellML, a
 * model of the Physiome Model Repository is a CellML model and becomes
 * SBML, so the two plots are the two languages of the same model.
 *
 * `docs/simulator/models.json` is the selection, which
 * `scripts/build_simulator_models.py` writes: every model of it passes
 * every stage of its check, and the file says which parameters the sliders
 * set (the id of the SBML parameter and the component and the variable of
 * CellML), which variables the plots show and what a variable is called on
 * the other side, so the page needs no analysis of its own.
 *
 * The modules of the two simulators are about 11 MB, which the page loads
 * when the section comes into view instead of when the page opens.
 */

(() => {
  "use strict";

  /** The chart of a plot and the helpers of `chart.js`. */
  const { COLORS, Chart, niceStep } = window.sbml2cellmlChart;

  /** The converter of the browser, `wasm.js`. */
  const { load: loadConverter, convert } = window.sbml2cellmlWasm;

  /** Where the JavaScript hosts of the two simulators are loaded from. */
  const CDN = "https://cdn.jsdelivr.net/npm";

  /** Where libopencor reads the document of a model of the page under.
   *
   * libopencor keeps a file by its URL, so every model of the page needs
   * its own: two documents under one URL are one file, whose contents are
   * the ones of the document which was read last, and a model of the page
   * is kept and simulated again when the visitor comes back to it.
   */
  const modelUrl = (id) => `https://sbml2cellml.local/${id}.cellml`;

  /** The settings of the solver, the ones of the python package. */
  const TOLERANCES = { relative: 1e-9, absolute: 1e-12, steps: 100000 };

  /** How long the sliders must rest before the simulations run again. */
  const DEBOUNCE = 60;

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
   * A value of a slider as text, with as few digits as it needs.
   *
   * @param {number} value The value.
   * @returns {string} The value, in the notation of an exponent when it is
   *   very large or very small.
   */
  function formatValue(value) {
    if (value === 0) {
      return "0";
    }
    const magnitude = Math.abs(value);
    if (magnitude >= 1e5 || magnitude < 1e-3) {
      return value.toExponential(2);
    }
    return String(Number(value.toPrecision(4)));
  }

  /**
   * The smallest nonzero magnitude of a value, which scales the tolerance.
   *
   * An absolute tolerance above the magnitude of a state makes its
   * trajectory meaningless, and the states of a model of a small
   * compartment are small, so both python packages scale the absolute
   * tolerance with the smallest initial value of a state when it is below
   * one, as roadrunner does, and the page simulates with their settings.
   *
   * @param {number[]} values The initial value of every state.
   * @returns {number} The smallest nonzero magnitude, `1` without one.
   */
  function smallest(values) {
    const magnitudes = values
      .map((value) => Math.abs(value))
      .filter((value) => value > 0 && Number.isFinite(value));
    return magnitudes.length === 0 ? 1 : Math.min(...magnitudes);
  }

  /** The modules of the two simulators, loaded once for the page. */
  let modules = null;

  /**
   * Load libopencor and sbmlsim-core, once for the page.
   *
   * @param {Object<string, string>} urls The URLs of the versions, the
   *   compiler, the engine and the math library of sbmlsim-core.
   * @returns {Promise<{opencor: object, compiler: object, runtime: object,
   *   versions: Object<string, string>}>} The two simulators.
   */
  async function loadSimulators(urls) {
    if (modules === null) {
      const versions = JSON.parse(await fetchText(urls.versions));
      const [opencorModule, { createCompiler }, { createRuntime }] =
        await Promise.all([
          import(
            `${CDN}/@opencor/libopencor@${versions.libopencor}/dist/libopencor.js`
          ),
          import(`${CDN}/sbmlsim-core@${versions["sbmlsim-core"]}/compile.mjs`),
          import(`${CDN}/sbmlsim-core@${versions["sbmlsim-core"]}/loader.mjs`),
        ]);
      const [opencor, compilerWasm, engine, mathlib] = await Promise.all([
        opencorModule.default(),
        fetchBytes(urls.compiler),
        fetchBytes(urls.engine),
        fetchBytes(urls.mathlib),
      ]);
      modules = {
        opencor,
        compiler: await createCompiler({ compiler: compilerWasm }),
        runtime: await createRuntime({ engine, mathlib }),
        versions,
      };
    }
    return modules;
  }

  /** The simulation of the CellML side of a model with libopencor. */
  class Cellml {
    /**
     * @param {object} library The module of libopencor.
     * @param {object} document_ The SED document of the model.
     * @param {object} solver The solver of the simulation.
     */
    constructor(library, document_, solver) {
      this.library = library;
      this.document = document_;
      this.model = document_.models.get(0);
      this.solver = solver;
      /** The scale of the absolute tolerance, from the first run. */
      this.scale = null;
    }

    /**
     * Read a CellML document and prepare its simulation.
     *
     * @param {object} library The module of libopencor.
     * @param {string} text The CellML document.
     * @param {{end: number, steps: number}} timecourse What to integrate.
     * @param {string} url The URL the document is read under, one per model.
     * @returns {Cellml} The simulation.
     */
    static create(library, text, timecourse, url) {
      const file = new library.File(url);
      file.setContents(new TextEncoder().encode(text));
      if (file.hasErrors) {
        throw new Error(file.issues.get(0).description);
      }
      const document_ = new library.SedDocument(file);
      const simulation = document_.simulations.get(0);
      simulation.initialTime = 0;
      simulation.outputStartTime = 0;
      simulation.outputEndTime = timecourse.end;
      simulation.numberOfSteps = timecourse.steps;
      const solver = new library.SolverCvode();
      solver.relativeTolerance = TOLERANCES.relative;
      solver.absoluteTolerance = TOLERANCES.absolute;
      solver.maximumNumberOfSteps = TOLERANCES.steps;
      simulation.odeSolver = solver;
      return new Cellml(library, document_, solver);
    }

    /**
     * Simulate the model with the values of the sliders.
     *
     * @param {Array<{component: string, variable: string}>} parameters The
     *   parameters of the sliders.
     * @param {number[]} values Their values, in the same order.
     * @param {Array<{label: string, cellml: string}>} series The variables
     *   of the plots.
     * @returns {{time: number[], series: Object<string, number[]>, units:
     *   Object<string, string>, voi: {name: string, unit: string},
     *   seconds: number}} The result by the label of a series.
     */
    run(parameters, values, series) {
      this.model.removeAllChanges();
      parameters.forEach((parameter, index) => {
        this.model.addChange(
          new this.library.SedChangeAttribute(
            parameter.component,
            parameter.variable,
            String(values[index]),
          ),
        );
      });
      const started = performance.now();
      let result = this.integrate(series);
      if (this.scale === null) {
        // the tolerance is scaled with the smallest initial value of a
        // state, as the python packages scale it, which a model of small
        // states needs; the scale of the published model is kept, since
        // the sliders change a value by a factor of at most two
        this.scale = smallest(result.initial);
        if (this.scale < 1) {
          this.solver.absoluteTolerance = TOLERANCES.absolute * this.scale;
          result = this.integrate(series);
        }
      }
      result.seconds = (performance.now() - started) / 1000;
      return result;
    }

    /**
     * Instantiate the document and read the variables of the plots.
     *
     * @param {Array<{label: string, cellml: string}>} series The variables
     *   of the plots.
     * @returns {object} The result, with the initial value of every state.
     */
    integrate(series) {
      const instance = this.document.instantiate();
      try {
        if (instance.hasIssues) {
          throw new Error(instance.issues.get(0).description);
        }
        instance.run();
        const task = instance.tasks.get(0);
        const names = new Map();
        const initial = [];
        for (let index = 0; index < task.stateCount; index += 1) {
          names.set(task.stateName(index), index);
          initial.push(task.state(index)[0]);
        }
        const values = {};
        const units = {};
        for (const entry of series) {
          const index = names.get(entry.cellml);
          if (index === undefined) {
            throw new Error(`the model has no variable ${entry.cellml}`);
          }
          // the arrays are views on the memory of the module, which the
          // instance gives back, so the values are copied out of them
          values[entry.label] = Array.from(task.state(index));
          units[entry.label] = task.stateUnit(index);
        }
        return {
          time: Array.from(task.voi),
          series: values,
          units,
          voi: { name: task.voiName, unit: task.voiUnit },
          initial,
          seconds: 0,
        };
      } finally {
        instance.delete();
      }
    }
  }

  /** The simulation of the SBML side of a model with sbmlsim-core. */
  class Sbml {
    /**
     * @param {object} instance The instance of the compiled model.
     * @param {{end: number, steps: number}} timecourse What to integrate.
     * @param {string[]} states The ids of the states, which scale the
     *   tolerance.
     */
    constructor(instance, timecourse, states) {
      this.instance = instance;
      this.timecourse = timecourse;
      this.states = states;
      /** The scale of the absolute tolerance, from the first run. */
      this.scale = null;
    }

    /**
     * Compile an SBML document in the browser and instantiate it.
     *
     * @param {object} core The compiler and the runtime of sbmlsim-core.
     * @param {string} sbml The SBML document.
     * @param {{end: number, steps: number}} timecourse What to integrate.
     * @returns {Promise<Sbml>} The simulation.
     */
    static async create(core, sbml, timecourse) {
      const { wasm, description } = core.compiler.compile(sbml);
      const instance = await core.runtime.instantiate(wasm, description);
      const states = (description.states ?? []).map((state) => state.id);
      return new Sbml(instance, timecourse, states);
    }

    /**
     * Simulate the model with the values of the sliders.
     *
     * @param {Array<{sbml: string}>} parameters The parameters of the
     *   sliders.
     * @param {number[]} values Their values, in the same order.
     * @param {Array<{label: string, sbml: string}>} series The variables of
     *   the plots.
     * @returns {{time: number[], series: Object<string, number[]>, seconds:
     *   number}} The result by the label of a series.
     */
    run(parameters, values, series) {
      const changes = parameters.map((parameter, index) => [
        parameter.sbml,
        values[index],
      ]);
      const selections = [
        "time",
        ...new Set([...series.map((entry) => entry.sbml), ...this.states]),
      ];
      const started = performance.now();
      let result = this.integrate(changes, selections, 1);
      if (this.scale === null) {
        // the first row of the result holds the initial value of a state
        const first = (name) => {
          const index = result.columns.indexOf(name);
          return index < 0 ? 0 : result.values[index];
        };
        this.scale = smallest(this.states.map(first));
        if (this.scale < 1) {
          result = this.integrate(changes, selections, this.scale);
        }
      }
      const seconds = (performance.now() - started) / 1000;
      // the values are the rows of the table, row major
      const width = result.columns.length;
      const column = (selection) => {
        const index = result.columns.indexOf(selection);
        if (index < 0) {
          return null;
        }
        return Array.from(
          { length: result.nRows },
          (_, row) => result.values[row * width + index],
        );
      };
      const values_ = {};
      for (const entry of series) {
        const column_ = column(entry.sbml);
        if (column_ === null) {
          throw new Error(`the model has no selection ${entry.sbml}`);
        }
        values_[entry.label] = column_;
      }
      return { time: column("time") ?? [], series: values_, seconds };
    }

    /**
     * Run one simulation of sbmlsim-core.
     *
     * @param {Array<[string, number]>} changes The value of every parameter.
     * @param {string[]} selections What the result holds.
     * @param {number} absolute The scale of the absolute tolerance.
     * @returns {object} The result of the simulator.
     */
    integrate(changes, selections, absolute) {
      return this.instance.simulate({
        contract: "simulation/1",
        start: 0,
        end: this.timecourse.end,
        output: { uniform: { steps: this.timecourse.steps } },
        // the parameters are set before the initial assignments are
        // evaluated, so the constants of the model follow the sliders
        preinit: changes,
        changes: [],
        steady_state: null,
        selections,
        settings: {
          relative_tolerance: TOLERANCES.relative,
          absolute_tolerance: { scalar: TOLERANCES.absolute * absolute },
          maximum_num_steps: TOLERANCES.steps,
          maximum_time_step: 0,
          initial_time_step: 0,
          stiff: true,
          linear_solver: "auto",
          jacobian: "auto",
        },
      });
    }
  }

  /** The online simulator of the page: a model, its sliders and its plots. */
  class Simulator {
    /**
     * @param {HTMLElement} root The element of the simulator.
     */
    constructor(root) {
      this.root = root;
      this.urls = {
        models: root.dataset.models,
        module: root.dataset.module,
        versions: root.dataset.versions,
        compiler: root.dataset.compiler,
        engine: root.dataset.engine,
        mathlib: root.dataset.mathlib,
      };
      this.choice = root.querySelector('[data-role="models"]');
      this.status = root.querySelector('[data-role="status"]');
      this.about = root.querySelector('[data-role="about"]');
      this.list = root.querySelector('[data-role="sliders"]');
      this.legend = root.querySelector('[data-role="legend"]');
      this.plots = root.querySelector('[data-role="plots"]');
      this.difference = root.querySelector('[data-role="difference"]');
      this.reset = root.querySelector('[data-action="reset"]');
      this.retry = root.querySelector('[data-action="retry"]');
      this.timings = {
        cellml: root.querySelector('[data-role="cellml-timing"]'),
        sbml: root.querySelector('[data-role="sbml-timing"]'),
      };
      this.charts = {
        cellml: new Chart(root.querySelector('[data-chart="cellml"]')),
        sbml: new Chart(root.querySelector('[data-chart="sbml"]')),
      };
      /** The models of the selection, the first one the one it opens with. */
      this.models = [];
      /** The models which are loaded, by their id. */
      this.loaded = new Map();
      /** The model of the plots. */
      this.current = null;
      /** The sliders of the model, in the order of the selection. */
      this.sliders = [];
      /** The series the legend hides. */
      this.hidden = new Set();
      /** The results of the last run, which the legend redraws. */
      this.results = null;
      /** The timeout which lets the sliders come to rest. */
      this.pending = null;
      /** The model which is being opened, so a slower one changes nothing. */
      this.generation = 0;
      this.choice.addEventListener("change", () => {
        void this.open(this.choice.value);
      });
      this.reset.addEventListener("click", () => this.restore());
      this.retry.addEventListener("click", () => void this.start());
    }

    /**
     * Say what the simulator is doing.
     *
     * @param {string} message The message.
     * @param {string} kind `"info"`, `"success"` or `"error"`.
     */
    say(message, kind) {
      this.status.dataset.kind = kind;
      this.status.textContent = message;
    }

    /** Read the selection and simulate the model the page opens with. */
    async start() {
      this.retry.hidden = true;
      this.say("Loading the two simulators, about 11 MB ...", "info");
      try {
        if (this.models.length === 0) {
          const manifest = JSON.parse(await fetchText(this.urls.models));
          this.models = manifest.models;
          this.fill();
        }
        await loadSimulators(this.urls);
        await this.open(this.models[0].id);
      } catch (error) {
        this.retry.hidden = false;
        this.say(`The simulation is not available: ${error.message}`, "error");
      }
    }

    /** Fill the dropdown of the models, one group per source. */
    fill() {
      const groups = new Map();
      for (const entry of this.models) {
        if (!groups.has(entry.source)) {
          const group = document.createElement("optgroup");
          group.label = entry.source;
          groups.set(entry.source, group);
        }
        const option = document.createElement("option");
        option.value = entry.id;
        option.textContent = entry.title;
        groups.get(entry.source).append(option);
      }
      this.choice.replaceChildren(...groups.values());
      this.choice.value = this.models[0].id;
    }

    /**
     * Load a model of the selection and simulate it.
     *
     * @param {string} id The id of the model.
     */
    async open(id) {
      const entry = this.models.find((model) => model.id === id);
      if (entry === undefined) {
        return;
      }
      this.generation += 1;
      const generation = this.generation;
      this.current = null;
      this.choice.disabled = true;
      this.setEnabled(false);
      this.describe(entry);
      try {
        if (!this.loaded.has(id)) {
          this.say(`Converting and compiling ${entry.title} ...`, "info");
          this.loaded.set(id, await this.build(entry));
        }
        if (generation !== this.generation) {
          // another model was chosen while this one was built
          return;
        }
        this.current = this.loaded.get(id);
        this.hidden = new Set();
        this.buildSliders(entry);
        this.buildLegend(entry);
        this.plots.hidden = false;
        this.setEnabled(true);
        const versions = modules.versions;
        this.say(
          `libopencor ${versions.libopencor} and sbmlsim-core ` +
            `${versions["sbmlsim-core"]} run in this browser.`,
          "success",
        );
        this.run();
      } catch (error) {
        if (generation === this.generation) {
          this.clear();
          this.say(`${entry.title} does not run: ${error.message}`, "error");
        }
      } finally {
        if (generation === this.generation) {
          this.choice.disabled = false;
        }
      }
    }

    /**
     * Convert a model of the selection and prepare both simulations.
     *
     * @param {object} entry The model of the selection.
     * @returns {Promise<{entry: object, cellml: Cellml, sbml: Sbml}>} The
     *   two simulations of the model.
     */
    async build(entry) {
      const text = await fetchText(entry.file);
      const wasm = await loadConverter(this.urls.module);
      const result = convert(wasm, entry.direction, text, entry.id);
      if (result.error) {
        throw new Error(result.error);
      }
      const cellml = entry.direction === "sbml2cellml" ? result.cellml : text;
      const sbml = entry.direction === "sbml2cellml" ? text : result.sbml;
      return {
        entry,
        cellml: Cellml.create(
          modules.opencor,
          cellml,
          entry.timecourse,
          modelUrl(entry.id),
        ),
        sbml: await Sbml.create(modules, sbml, entry.timecourse),
      };
    }

    /**
     * Say which model the plots show and where it comes from.
     *
     * @param {object} entry The model of the selection.
     */
    describe(entry) {
      const link = document.createElement("a");
      link.href = entry.url;
      link.textContent = entry.id;
      link.target = "_blank";
      link.rel = "noopener";
      const conversion =
        entry.direction === "sbml2cellml"
          ? "an SBML model, converted to CellML in this page"
          : "a CellML model, converted to SBML in this page";
      this.about.replaceChildren(
        document.createTextNode(`${entry.source} `),
        link,
        document.createTextNode(`, ${conversion}.`),
      );
    }

    /**
     * Let the visitor use the sliders, or wait until a model is loaded.
     *
     * @param {boolean} enabled Whether the model is ready.
     */
    setEnabled(enabled) {
      for (const slider of this.sliders) {
        slider.input.disabled = !enabled;
      }
      this.reset.disabled = !enabled;
    }

    /**
     * Build one slider per parameter of a model.
     *
     * @param {object} entry The model of the selection.
     */
    buildSliders(entry) {
      this.sliders = [];
      const items = entry.parameters.map((parameter) => {
        const item = document.createElement("div");
        item.className = "simulator__slider";
        const label = document.createElement("label");
        const id = `simulator-${entry.id}-${parameter.sbml}`;
        label.className = "simulator__label";
        label.setAttribute("for", id);
        const name = parameter.name ? `, ${parameter.name}` : "";
        const unit = parameter.unit ? ` (${parameter.unit})` : "";
        label.textContent = `${parameter.label}${name}${unit}`;
        label.title = label.textContent;
        const readout = document.createElement("output");
        readout.className = "simulator__value";
        readout.setAttribute("for", id);
        const input = document.createElement("input");
        input.id = id;
        input.type = "range";
        input.min = String(parameter.minimum);
        input.max = String(parameter.maximum);
        input.step = String(parameter.step);
        input.value = String(parameter.value);
        const show = () => {
          readout.textContent = formatValue(Number(input.value));
        };
        show();
        input.addEventListener("input", () => {
          show();
          this.schedule();
        });
        const head = document.createElement("div");
        head.className = "simulator__head";
        head.append(label, readout);
        item.append(head, input);
        this.sliders.push({ parameter, input, show });
        return item;
      });
      this.list.replaceChildren(...items);
    }

    /** Set every slider back to the value of the published model. */
    restore() {
      for (const { parameter, input, show } of this.sliders) {
        input.value = String(parameter.value);
        show();
      }
      this.run();
    }

    /** Simulate again when the sliders have come to rest. */
    schedule() {
      if (this.current === null) {
        return;
      }
      if (this.pending !== null) {
        clearTimeout(this.pending);
      }
      this.pending = setTimeout(() => {
        this.pending = null;
        this.run();
      }, DEBOUNCE);
    }

    /** Simulate both sides of the model with the values of the sliders. */
    run() {
      if (this.current === null) {
        return;
      }
      const { entry, cellml, sbml } = this.current;
      const parameters = this.sliders.map((slider) => slider.parameter);
      const values = this.sliders.map((slider) => Number(slider.input.value));
      try {
        const left = cellml.run(parameters, values, entry.series);
        const right = sbml.run(parameters, values, entry.series);
        this.results = { cellml: left, sbml: right };
        this.timings.cellml.textContent = formatTime(left.seconds * 1000);
        this.timings.sbml.textContent = formatTime(right.seconds * 1000);
        this.draw();
      } catch (error) {
        this.clear();
        this.say(`The simulation failed: ${error.message}`, "error");
      }
    }

    /** Hide the plots, which hold the result of another model otherwise. */
    clear() {
      this.results = null;
      this.plots.hidden = true;
      this.difference.textContent = "";
      this.timings.cellml.textContent = "-";
      this.timings.sbml.textContent = "-";
    }

    /**
     * Build the legend, whose items show and hide their series.
     *
     * @param {object} entry The model of the selection.
     */
    buildLegend(entry) {
      this.legend.replaceChildren(
        ...entry.series.map((series, index) => {
          const item = document.createElement("button");
          item.type = "button";
          item.className = "simulator__legend-item";
          item.setAttribute("aria-pressed", "true");
          item.title = `Hide ${series.label}`;
          const swatch = document.createElement("span");
          swatch.className = "simulator__swatch";
          swatch.style.background = COLORS[index % COLORS.length];
          item.append(swatch, document.createTextNode(series.label));
          item.addEventListener("click", () => this.toggle(series, item));
          return item;
        }),
      );
    }

    /**
     * Show or hide a series of both plots.
     *
     * @param {{label: string}} series The series of the legend.
     * @param {HTMLButtonElement} item Its item of the legend.
     */
    toggle(series, item) {
      const count = this.current.entry.series.length;
      if (this.hidden.has(series.label)) {
        this.hidden.delete(series.label);
      } else if (this.hidden.size + 1 < count) {
        // the last series of the plots stays, so a plot is never empty
        this.hidden.add(series.label);
      } else {
        return;
      }
      const shown = !this.hidden.has(series.label);
      item.setAttribute("aria-pressed", String(shown));
      item.title = `${shown ? "Hide" : "Show"} ${series.label}`;
      this.draw();
    }

    /** Draw both results, the two plots on the same axes. */
    draw() {
      if (this.results === null || this.current === null) {
        return;
      }
      const { entry } = this.current;
      const { cellml, sbml } = this.results;
      const series = entry.series
        .map((entry_, index) => ({
          id: entry_.label,
          label: entry_.label,
          color: COLORS[index % COLORS.length],
        }))
        .filter((entry_) => !this.hidden.has(entry_.id));
      let minimum = 0;
      let maximum = 0;
      for (const result of [cellml, sbml]) {
        for (const entry_ of series) {
          for (const value of result.series[entry_.id] ?? []) {
            if (Number.isFinite(value)) {
              minimum = Math.min(minimum, value);
              maximum = Math.max(maximum, value);
            }
          }
        }
      }
      if (maximum <= minimum) {
        maximum = minimum + 1;
      }
      const step = niceStep(maximum - minimum, 4);
      const labels = this.labels(cellml, series);
      const options = {
        series,
        range: { start: 0, end: entry.timecourse.end },
        maximum: Math.ceil(maximum / step) * step,
        minimum: Math.floor(minimum / step) * step,
        labels,
      };
      this.charts.cellml.show(cellml, options);
      this.charts.sbml.show(sbml, options);
      this.difference.textContent =
        "The largest difference between the two simulations over the series " +
        `of the plots: ${this.largest(series).toExponential(1)}.`;
    }

    /**
     * The labels of the axes of the plots.
     *
     * @param {object} result The result of the CellML simulation, which has
     *   the units of the model.
     * @param {Array<{id: string}>} series The series of the plots.
     * @returns {{x: string, y: string}} The labels, with the units of the
     *   model when every series has the same ones.
     */
    labels(result, series) {
      const units = new Set(series.map((entry) => result.units[entry.id]));
      const suffix = (unit) =>
        unit && unit !== "dimensionless" ? ` (${unit})` : "";
      // the name of a variable of libopencor is `component/variable`
      const name = result.voi.name.split("/").pop();
      return {
        x: `${name}${suffix(result.voi.unit)}`,
        y: units.size === 1 ? `value${suffix([...units][0])}` : "value",
      };
    }

    /**
     * The largest difference between the two simulations.
     *
     * @param {Array<{id: string}>} series The series of the plots.
     * @returns {number} The largest difference over the series, `0` without
     *   a comparable value.
     */
    largest(series) {
      const { cellml, sbml } = this.results;
      let largest = 0;
      for (const entry of series) {
        const left = cellml.series[entry.id] ?? [];
        const right = sbml.series[entry.id] ?? [];
        const count = Math.min(left.length, right.length);
        for (let index = 0; index < count; index += 1) {
          const difference = Math.abs(left[index] - right[index]);
          if (Number.isFinite(difference)) {
            largest = Math.max(largest, difference);
          }
        }
      }
      return largest;
    }
  }

  /**
   * Start the simulator of the page.
   *
   * The two simulators are about 11 MB, which the page loads when the
   * section comes into view: a visitor who reads the top of the page pays
   * nothing for it, and one who scrolls to the section finds it running.
   */
  function start() {
    for (const root of document.querySelectorAll("[data-simulator]")) {
      if (root.dataset.started === "true") {
        continue;
      }
      root.dataset.started = "true";
      const simulator = new Simulator(root);
      const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          void simulator.start();
        }
      });
      observer.observe(root);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
