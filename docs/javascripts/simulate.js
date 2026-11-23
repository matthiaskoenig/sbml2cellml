/* The simulation of the online converter, which runs in the browser.
 *
 * The converter of the landing page writes the CellML of an SBML model and
 * the SBML of a CellML model in the browser (`converter.js`, the WebAssembly
 * module of the rust converters). This file simulates both sides of a
 * conversion there as well: libopencor reads the CellML document out of the
 * memory of the page and integrates it with CVODE, sbmlsim-core compiles the
 * SBML document in the browser (`compiler.wasm`, the compiler of its command
 * line as WebAssembly) and integrates it, and the two timecourses are drawn
 * next to each other on two canvases (`chart.js`) with the largest
 * difference between them. Nothing is uploaded and no server sees the model.
 *
 * The versions of the two simulators are the versions of the python
 * packages, which `scripts/build_simulation.py` writes to
 * `docs/roundtrip/simulation/versions.json` next to the modules of
 * sbmlsim-core, so the browser runs the simulators the checks of the
 * repository run. Without that file, which the `documentation` workflow
 * writes, the page says that the simulation is not available, and a release
 * of sbmlsim-core before 0.23.0 has no compiler in the browser, which leaves
 * the SBML side out.
 */

(() => {
  "use strict";

  /** The CDN both pages load the simulators from. */
  const CDN = "https://cdn.jsdelivr.net/npm";

  /** The versions of the simulators, written by the build script. */
  const VERSIONS = "roundtrip/simulation/versions.json";

  /** Where the modules of the simulation of the page are, next to the versions. */
  const ASSETS = "roundtrip/simulation";

  /** The URL libopencor reads the document of the page under. */
  const MODEL_URL = "https://sbml2cellml.local/model.cellml";

  /** The settings of the solver, the ones of the python package. */
  const TOLERANCES = { relative: 1e-9, absolute: 1e-12, steps: 100000 };

  /** The largest number of variables the plot shows. */
  const SERIES = 8;

  /** The module of libopencor, loaded once for the page. */
  let library = null;

  /** The compiler and the runtime of sbmlsim-core, loaded once for the page. */
  let sbmlsim = null;

  /**
   * The text of a file of the site.
   *
   * @param {string} url The URL of the file.
   * @returns {Promise<string>} Its text.
   */
  async function fetchText(url) {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`${url} is not available (${response.status})`);
    }
    return await response.text();
  }

  /**
   * The module of libopencor, loaded and instantiated once.
   *
   * @param {string} base The base URL of the versions file.
   * @returns {Promise<object>} The module.
   */
  async function load(base) {
    if (library === null) {
      const module = await import(
        `${CDN}/@opencor/libopencor@${(await versions()).libopencor}/dist/libopencor.js`
      );
      library = await module.default();
      library.version = (await versions()).libopencor;
    }
    return library;
  }

  /** The versions of the simulators of the page, fetched once. */
  let theVersions = null;

  /**
   * The versions of the two simulators, which the build script wrote.
   *
   * @returns {Promise<Object<string, string>>} The version by package.
   */
  async function versions() {
    if (theVersions === null) {
      theVersions = JSON.parse(
        await fetchText(new URL(VERSIONS, document.baseURI)),
      );
    }
    return theVersions;
  }

  /**
   * The bytes of a file of the site.
   *
   * @param {string} url The URL of the file.
   * @returns {Promise<Uint8Array>} Its bytes.
   */
  async function fetchBytes(url) {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`${url} is not available (${response.status})`);
    }
    return new Uint8Array(await response.arrayBuffer());
  }

  /**
   * The compiler and the runtime of sbmlsim-core, loaded once for the page.
   *
   * The host is the npm package of the version of the python package, the
   * modules are the ones `scripts/build_simulation.py` wrote next to the
   * versions: a release of sbmlsim-core without `compiler.wasm` (before
   * 0.23.0) has no compiler in the browser, and the page then simulates the
   * CellML side of a conversion alone.
   *
   * @returns {Promise<{compiler: object, runtime: object, version: string}>}
   *   The compiler, the runtime and the version of sbmlsim-core.
   */
  async function loadSbmlsim() {
    if (sbmlsim === null) {
      const version = (await versions())["sbmlsim-core"];
      const [{ createCompiler }, { createRuntime }] = await Promise.all([
        import(`${CDN}/sbmlsim-core@${version}/compile.mjs`),
        import(`${CDN}/sbmlsim-core@${version}/loader.mjs`),
      ]);
      const base = new URL(`${ASSETS}/`, document.baseURI);
      const [compiler, engine, mathlib] = await Promise.all([
        fetchBytes(new URL("compiler.wasm", base)),
        fetchBytes(new URL("engine.wasm", base)),
        fetchBytes(new URL("mathlib.wasm", base)),
      ]);
      sbmlsim = {
        compiler: await createCompiler({ compiler }),
        runtime: await createRuntime({ engine, mathlib }),
        version,
      };
    }
    return sbmlsim;
  }

  /**
   * Simulate a CellML document with libopencor.
   *
   * @param {object} opencor The module of libopencor.
   * @param {string} text The CellML document.
   * @param {{end: number, steps: number}} timecourse What to integrate.
   * @returns {{time: number[], series: Object<string, number[]>,
   *   names: string[], seconds: number}} The result, the names of its
   *   series in the order of the model and the wall time of the run.
   */
  function simulate(opencor, text, timecourse, absolute = 1) {
    const file = new opencor.File(MODEL_URL);
    file.setContents(new TextEncoder().encode(text));
    if (file.hasErrors) {
      throw new Error(file.issues.get(0).description);
    }
    const document_ = new opencor.SedDocument(file);
    const simulation = document_.simulations.get(0);
    simulation.initialTime = 0;
    simulation.outputStartTime = 0;
    simulation.outputEndTime = timecourse.end;
    simulation.numberOfSteps = timecourse.steps;
    const solver = new opencor.SolverCvode();
    solver.relativeTolerance = TOLERANCES.relative;
    solver.absoluteTolerance = TOLERANCES.absolute * absolute;
    solver.maximumNumberOfSteps = TOLERANCES.steps;
    simulation.odeSolver = solver;
    const instance = document_.instantiate();
    try {
      if (instance.hasIssues) {
        throw new Error(instance.issues.get(0).description);
      }
      const started = performance.now();
      instance.run();
      const seconds = (performance.now() - started) / 1000;
      const task = instance.tasks.get(0);
      const names = [];
      const series = {};
      const units = {};
      // the states of the model, whose name is `component/variable`
      for (let index = 0; index < task.stateCount; index += 1) {
        const name = task.stateName(index);
        names.push(name);
        units[name] = task.stateUnit(index);
        // the arrays are views on the memory of the module, which the
        // instance gives back, so the values are copied out of them
        series[name] = Array.from(task.state(index));
      }
      return {
        time: Array.from(task.voi),
        series,
        names,
        units,
        voi: { name: task.voiName, unit: task.voiUnit },
        seconds,
        // the initial value of every state, which scales the tolerance
        scale: smallest(names.map((name) => series[name][0])),
      };
    } finally {
      instance.delete();
    }
  }

  /**
   * The smallest nonzero magnitude of a value, which scales the tolerance.
   *
   * An absolute tolerance above the magnitude of a state makes its
   * trajectory meaningless, and the states of a model of a small
   * compartment are small: a species with a concentration of 1 in a
   * compartment of 1e-13 litre has the amount 1e-13, which the solver of
   * SBML integrates. Both python packages scale the absolute tolerance with
   * the smallest initial value of a state when it is below one, as
   * roadrunner does, and the page simulates with the settings of the python
   * packages.
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

  /**
   * The selection of sbmlsim-core which holds the variable of CellML.
   *
   * The conversion writes a species as the variable of its concentration,
   * or of its amount when the species has only substance units, and gives a
   * species in a compartment which changes a second variable
   * `<species>_amount` which the state of the model is. sbmlsim-core selects
   * the amount of a species by its id and the concentration as `[id]`, so
   * the two sides of a conversion are compared variable by variable.
   *
   * @param {string} name The name of the variable of the CellML model.
   * @param {Object<string, object>} species The species of the SBML model by
   *   their id, from the description of the compiled model.
   * @returns {string|null} The selection, `null` for a variable the SBML
   *   model does not have.
   */
  function selectionOf(name, species) {
    if (name.endsWith("_amount") && species[name.slice(0, -"_amount".length)]) {
      return name.slice(0, -"_amount".length);
    }
    const kind = species[name];
    if (kind === undefined) {
      // a parameter, a compartment or the rate of a reaction keeps its id
      return name;
    }
    return kind.has_only_substance_units ? name : `[${name}]`;
  }

  /**
   * The species of a compiled model by their id.
   *
   * @param {object} description The description of the compiled model.
   * @returns {Object<string, object>} The kind of every species.
   */
  function speciesOf(description) {
    const species = {};
    for (const entry of [
      ...(description.states ?? []),
      ...(description.parameters ?? []),
    ]) {
      if (entry.kind && entry.kind.species) {
        species[entry.id] = entry.kind.species;
      }
    }
    return species;
  }

  /**
   * Compiles an SBML document and simulates it with sbmlsim-core.
   *
   * @param {object} core The compiler and the runtime of sbmlsim-core.
   * @param {string} sbml The SBML document.
   * @param {string[]} names The variables of the CellML result, whose
   *   counterparts the simulation selects.
   * @param {{end: number, steps: number}} timecourse What to integrate.
   * @returns {Promise<{series: Object<string, number[]>, time: number[],
   *   seconds: number}>} The result by the name of the CellML variable.
   */
  async function simulateSbml(core, sbml, names, timecourse) {
    const { wasm, description } = core.compiler.compile(sbml);
    const instance = await core.runtime.instantiate(wasm, description);
    const species = speciesOf(description);
    const selections = new Map();
    for (const name of names) {
      const selection = selectionOf(name, species);
      if (selection !== null) {
        selections.set(name, selection);
      }
    }
    // the states of the model are its amounts, whose first values scale the
    // absolute tolerance, as `sbmlsim.state_scale` of the python package does
    const states = (description.states ?? []).map((state) => state.id);
    const columns = ["time", ...new Set([...selections.values(), ...states])];
    const run = (absolute) =>
      instance.simulate({
        contract: "simulation/1",
        start: 0,
        end: timecourse.end,
        output: { uniform: { steps: timecourse.steps } },
        preinit: [],
        changes: [],
        steady_state: null,
        selections: columns,
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
    const started = performance.now();
    let result = run(1);
    const first = (name) => {
      const index = result.columns.indexOf(name);
      return index < 0 ? 0 : result.values[index];
    };
    const scale = smallest(states.map(first));
    if (scale < 1) {
      result = run(scale);
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
    const series = {};
    for (const [name, selection] of selections) {
      const values = column(selection);
      if (values !== null) {
        series[name] = values;
      }
    }
    return { time: column("time") ?? [], series, seconds };
  }

  /**
   * The largest difference between two results over the series both have.
   *
   * @param {{series: Object<string, number[]>}} left The one result.
   * @param {{series: Object<string, number[]>}} right The other one.
   * @param {Array<{id: string, label: string}>} series The series of the plot.
   * @returns {number|null} The difference, `null` when nothing is shared.
   */
  function largestDifference(left, right, series) {
    let largest = null;
    for (const entry of series) {
      const here = left.series[entry.id];
      const there = right.series[entry.label];
      if (here === undefined || there === undefined) {
        continue;
      }
      const rows = Math.min(here.length, there.length);
      for (let row = 0; row < rows; row += 1) {
        const difference = Math.abs(here[row] - there[row]);
        if (Number.isFinite(difference)) {
          largest =
            largest === null ? difference : Math.max(largest, difference);
        }
      }
    }
    return largest;
  }

  /**
   * The name of a variable of libopencor without its component.
   *
   * @param {string} name The name, which is `component/variable`.
   * @returns {string} The name of the variable.
   */
  function variableName(name) {
    const slash = name.indexOf("/");
    return slash < 0 ? name : name.slice(slash + 1);
  }

  /**
   * The labels of the states, as `simulate._result_names` writes them.
   *
   * The `component/variable` of libopencor becomes the name of the
   * variable, which is what a model of one component needs; a name which
   * more than one state has keeps its component, so the states of a model
   * of many components stay apart.
   *
   * @param {string[]} names The names of the states of the result.
   * @returns {Object<string, string>} The label of every name.
   */
  function labelsOfStates(names) {
    const count = new Map();
    for (const name of names) {
      const short = variableName(name);
      count.set(short, (count.get(short) ?? 0) + 1);
    }
    return Object.fromEntries(
      names.map((name) => {
        const short = variableName(name);
        return [name, count.get(short) === 1 ? short : name];
      }),
    );
  }

  /**
   * The series of a result, up to `SERIES` of them with their colors.
   *
   * @param {{names: string[], series: Object<string, number[]>}} result The
   *   result of a simulation.
   * @returns {Array<{id: string, label: string, color: string}>} The series.
   */
  function seriesOf(result) {
    const colors = window.sbml2cellmlChart.COLORS;
    const labels = labelsOfStates(result.names);
    return result.names.slice(0, SERIES).map((name, index) => ({
      id: name,
      label: labels[name],
      color: colors[index % colors.length],
    }));
  }

  /**
   * The range of the values of the series of a plot.
   *
   * @param {{series: Object<string, number[]>}} result The result.
   * @param {Array<{id: string}>} series The series of the plot.
   * @returns {{minimum: number, maximum: number}} The range, which is never
   *   empty.
   */
  function rangeOf(result, series) {
    let minimum = 0;
    let maximum = 0;
    for (const entry of series) {
      for (const value of result.series[entry.id]) {
        if (Number.isFinite(value)) {
          minimum = Math.min(minimum, value);
          maximum = Math.max(maximum, value);
        }
      }
    }
    if (maximum <= minimum) {
      maximum = minimum + 1;
    }
    return { minimum, maximum };
  }

  /**
   * The units of a quantity in brackets, nothing for a dimensionless one.
   *
   * @param {string} unit The units of the model.
   * @returns {string} The suffix of the label.
   */
  function unitSuffix(unit) {
    return unit && unit !== "dimensionless" ? ` (${unit})` : "";
  }

  /**
   * The labels of the axes of a result.
   *
   * @param {{units: Object<string, string>, voi: {name: string, unit:
   *   string}}} result The result of a simulation.
   * @param {Array<{id: string}>} series The series of the plot.
   * @returns {{x: string, y: string}} The labels, with the units of the
   *   model when every series has the same ones.
   */
  function labelsOf(result, series) {
    const units = new Set(series.map((entry) => result.units[entry.id]));
    return {
      x: `${variableName(result.voi.name)}${unitSuffix(result.voi.unit)}`,
      y: units.size === 1 ? `value${unitSuffix([...units][0])}` : "value",
    };
  }

  /** The simulation of one panel of the converter, both sides of a conversion. */
  class Simulator {
    /**
     * @param {HTMLElement} root The element of the simulation of the panel.
     */
    constructor(root) {
      this.root = root;
      this.status = root.querySelector('[data-role="simulation-status"]');
      this.button = root.querySelector('[data-action="simulate"]');
      this.end = root.querySelector('[data-role="end"]');
      this.steps = root.querySelector('[data-role="steps"]');
      this.legend = root.querySelector('[data-role="legend"]');
      this.plots = root.querySelector('[data-role="plots"]');
      this.sbmlPlot = root.querySelector('[data-role="plot-sbml"]');
      this.difference = root.querySelector('[data-role="difference"]');
      const labels = { x: "time", y: "value" };
      this.charts = {
        cellml: new window.sbml2cellmlChart.Chart(
          root.querySelector('[data-role="plot-cellml"] canvas'),
          labels,
        ),
        sbml: new window.sbml2cellmlChart.Chart(
          root.querySelector('[data-role="plot-sbml"] canvas'),
          labels,
        ),
      };
      /** The two documents of the conversion, which the button simulates. */
      this.models = null;
      /** The results of the last run, which the legend redraws. */
      this.results = null;
      this.timecourse = { end: 1, steps: 1 };
      this.series = [];
      this.hidden = new Set();
      this.button.addEventListener("click", () => void this.run());
    }

    /**
     * Take the two documents of the conversion of the panel.
     *
     * @param {{cellml: string, sbml: string}|null} models The CellML and the
     *   SBML document, `null` when the panel has none.
     */
    setModel(models) {
      this.models = models;
      this.root.hidden = models === null;
      this.button.disabled = models === null;
      if (models === null) {
        this.reset();
      }
    }

    /** Forget the results of an earlier run. */
    reset() {
      this.plots.hidden = true;
      this.sbmlPlot.hidden = true;
      this.difference.hidden = true;
      this.legend.replaceChildren();
      this.results = null;
      this.show("", "info");
    }

    /**
     * Show a status line.
     *
     * @param {string} message The message, which empties the line.
     * @param {string} kind `info`, `error` or `success`.
     */
    show(message, kind) {
      this.status.textContent = message;
      this.status.dataset.kind = kind;
    }

    /** Simulate both documents of the panel and draw the results. */
    async run() {
      if (this.models === null) {
        return;
      }
      const timecourse = {
        end: Number(this.end.value) || 1,
        steps: Math.min(Math.max(Number(this.steps.value) || 100, 1), 10000),
      };
      this.button.disabled = true;
      this.show("Simulating ...", "info");
      try {
        const opencor = await load(VERSIONS);
        let cellml = simulate(opencor, this.models.cellml, timecourse);
        if (cellml.scale < 1) {
          // libopencor fills the arrays of the states only when it runs, so
          // the model is run once more with the scaled tolerance, as the
          // python package does
          cellml = simulate(
            opencor,
            this.models.cellml,
            timecourse,
            cellml.scale,
          );
        }
        if (cellml.names.length === 0) {
          this.reset();
          this.show(
            "The model has no differential equation, there is nothing to " +
              "integrate: the python package runs such a model as a steady " +
              "state.",
            "info",
          );
          return;
        }
        this.results = { cellml, sbml: null };
        this.timecourse = timecourse;
        this.series = seriesOf(cellml);
        this.hidden = new Set();
        this.buildLegend();
        this.plots.hidden = false;
        const lines = [
          `libopencor ${opencor.version} integrated ${cellml.names.length} ` +
            `state${cellml.names.length === 1 ? "" : "s"} in ` +
            `${(cellml.seconds * 1000).toFixed(0)} ms`,
        ];
        const sbml = await this.runSbml(timecourse, lines);
        this.results.sbml = sbml;
        this.sbmlPlot.hidden = sbml === null;
        const shown = Math.min(cellml.names.length, SERIES);
        const of =
          cellml.names.length > shown ? ` of ${cellml.names.length}` : "";
        this.draw();
        this.show(`${lines.join(", ")}; ${shown}${of} shown.`, "success");
      } catch (error) {
        this.reset();
        this.show(`The simulation failed: ${error.message}`, "error");
      } finally {
        this.button.disabled = false;
      }
    }

    /**
     * Simulate the SBML side with sbmlsim-core, which compiles it first.
     *
     * A release of sbmlsim-core without the compiler in the browser, and a
     * model it refuses, leave the SBML side out: the CellML side is drawn
     * alone and the status says why.
     *
     * @param {{end: number, steps: number}} timecourse What to integrate.
     * @param {string[]} lines What the status line says of the run.
     * @returns {Promise<object|null>} The result, `null` without one.
     */
    async runSbml(timecourse, lines) {
      let core = null;
      try {
        core = await loadSbmlsim();
      } catch {
        lines.push("sbmlsim-core does not compile in the browser yet");
        return null;
      }
      try {
        const result = await simulateSbml(
          core,
          this.models.sbml,
          this.series.map((entry) => entry.label),
          timecourse,
        );
        lines.push(
          `sbmlsim-core ${core.version} integrated the SBML model in ` +
            `${(result.seconds * 1000).toFixed(0)} ms`,
        );
        return result;
      } catch (error) {
        lines.push(`sbmlsim-core refused the SBML model (${error.message})`);
        return null;
      }
    }

    /** Build the legend, whose items show and hide their series. */
    buildLegend() {
      this.legend.replaceChildren(
        ...this.series.map((entry) => {
          // a series of the plots is shown or hidden with its legend, so a
          // state of a model of many states is read next to its own axis
          const item = document.createElement("button");
          item.type = "button";
          item.className = "converter__legend-item";
          item.setAttribute("aria-pressed", "true");
          item.title = `Hide ${entry.label}`;
          const swatch = document.createElement("span");
          swatch.className = "converter__swatch";
          swatch.style.background = entry.color;
          item.append(swatch, document.createTextNode(entry.label));
          item.addEventListener("click", () => this.toggle(entry, item));
          return item;
        }),
      );
    }

    /**
     * Show or hide a series of the plots.
     *
     * @param {{id: string, label: string}} entry The series of the legend.
     * @param {HTMLButtonElement} item Its item of the legend.
     */
    toggle(entry, item) {
      const hidden = this.hidden.has(entry.id);
      if (hidden) {
        this.hidden.delete(entry.id);
      } else if (this.hidden.size + 1 < this.series.length) {
        // the last series of the plots stays, so a plot is never empty
        this.hidden.add(entry.id);
      } else {
        return;
      }
      const shown = !this.hidden.has(entry.id);
      item.setAttribute("aria-pressed", String(shown));
      item.title = `${shown ? "Hide" : "Show"} ${entry.label}`;
      this.draw();
    }

    /** Draw the series which are not hidden, both sides on the same axis. */
    draw() {
      if (this.results === null) {
        return;
      }
      const { cellml, sbml } = this.results;
      const series = this.series.filter((entry) => !this.hidden.has(entry.id));
      const range = rangeOf(cellml, series);
      // the series of the SBML result are the names of the CellML variables
      const theirs = series.map((entry) => ({ ...entry, id: entry.label }));
      if (sbml !== null) {
        const other = rangeOf(sbml, theirs);
        range.minimum = Math.min(range.minimum, other.minimum);
        range.maximum = Math.max(range.maximum, other.maximum);
      }
      const options = {
        series,
        range: { start: 0, end: this.timecourse.end },
        maximum: range.maximum,
        minimum: range.minimum,
        labels: labelsOf(cellml, series),
      };
      this.charts.cellml.show(cellml, options);
      if (sbml !== null) {
        this.charts.sbml.show(sbml, { ...options, series: theirs });
        const largest = largestDifference(cellml, sbml, series);
        this.difference.hidden = largest === null;
        this.difference.textContent =
          largest === null
            ? ""
            : "The largest difference between the two simulations over the " +
              `series of the plots: ${largest.toExponential(1)}.`;
      } else {
        this.difference.hidden = true;
      }
    }
  }

  window.sbml2cellmlSimulate = { Simulator };
})();
