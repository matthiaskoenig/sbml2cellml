/* The simulation of the online converter, which runs in the browser.
 *
 * The converter of the landing page writes the CellML of an SBML model and
 * the SBML of a CellML model in the browser (`converter.js`, the WebAssembly
 * module of the rust converters). This file simulates the CellML side of a
 * conversion there as well: libopencor is loaded from a CDN when the visitor
 * simulates the first model, reads the document out of the memory of the
 * page and integrates it with CVODE, and the timecourse of every state is
 * drawn on a canvas (`chart.js`). Nothing is uploaded and no server sees the
 * model.
 *
 * The version of libopencor is the version of the python package, which
 * `scripts/build_simulation.py` writes to
 * `docs/roundtrip/simulation/versions.json`, so the browser runs the
 * simulator the checks of the repository run. Without that file, which the
 * `documentation` workflow writes, the page says that the simulation is not
 * available.
 *
 * The SBML side of a conversion cannot be simulated in the browser yet:
 * sbmlsim-core compiles an SBML model into a WebAssembly module ahead of
 * time and its compiler is not part of its JavaScript host, see the
 * documentation of the page.
 */

(() => {
  "use strict";

  /** The CDN both pages load the simulators from. */
  const CDN = "https://cdn.jsdelivr.net/npm";

  /** The versions of the simulators, written by the build script. */
  const VERSIONS = "roundtrip/simulation/versions.json";

  /** The URL libopencor reads the document of the page under. */
  const MODEL_URL = "https://sbml2cellml.local/model.cellml";

  /** The settings of the solver, the ones of the python package. */
  const TOLERANCES = { relative: 1e-9, absolute: 1e-12, steps: 100000 };

  /** The largest number of variables the plot shows. */
  const SERIES = 8;

  /** The module of libopencor, loaded once for the page. */
  let library = null;

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
      const versions = JSON.parse(
        await fetchText(new URL(base, document.baseURI)),
      );
      const module = await import(
        `${CDN}/@opencor/libopencor@${versions.libopencor}/dist/libopencor.js`
      );
      library = await module.default();
      library.version = versions.libopencor;
    }
    return library;
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
  function simulate(opencor, text, timecourse) {
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
    solver.absoluteTolerance = TOLERANCES.absolute;
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
      };
    } finally {
      instance.delete();
    }
  }

  /**
   * The name of a variable of libopencor without its component.
   *
   * @param {string} name The name, which is `component/variable`.
   * @returns {string} The name of the variable, which the plot labels.
   */
  function variableName(name) {
    const slash = name.indexOf("/");
    return slash < 0 ? name : name.slice(slash + 1);
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
    return result.names.slice(0, SERIES).map((name, index) => ({
      id: name,
      label: variableName(name),
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

  /** The simulation of one panel of the converter. */
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
      this.plot = root.querySelector('[data-role="plot"]');
      this.chart = new window.sbml2cellmlChart.Chart(
        root.querySelector("canvas"),
        { x: "time", y: "value" },
      );
      this.text = null;
      this.button.addEventListener("click", () => void this.run());
    }

    /**
     * Take the CellML document of the panel, which the button simulates.
     *
     * @param {string|null} text The document, `null` when the panel has none.
     */
    setModel(text) {
      this.text = text;
      this.root.hidden = text === null;
      this.button.disabled = text === null;
      if (text === null) {
        this.reset();
      }
    }

    /** Forget the result of an earlier run. */
    reset() {
      this.plot.hidden = true;
      this.legend.replaceChildren();
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

    /** Simulate the document of the panel and draw the result. */
    async run() {
      if (this.text === null) {
        return;
      }
      const timecourse = {
        end: Number(this.end.value) || 1,
        steps: Math.min(Math.max(Number(this.steps.value) || 100, 1), 10000),
      };
      this.button.disabled = true;
      this.show("Simulating with libopencor ...", "info");
      try {
        const opencor = await load(VERSIONS);
        const result = simulate(opencor, this.text, timecourse);
        if (result.names.length === 0) {
          this.plot.hidden = true;
          this.legend.replaceChildren();
          this.show(
            "The model has no differential equation, there is nothing to " +
              "integrate: the python package runs such a model as a steady " +
              "state.",
            "info",
          );
          return;
        }
        this.draw(result, timecourse);
        const shown = Math.min(result.names.length, SERIES);
        const of =
          result.names.length > shown ? ` of ${result.names.length}` : "";
        this.show(
          `libopencor ${opencor.version} integrated ${result.names.length} ` +
            `state${result.names.length === 1 ? "" : "s"} to ` +
            `${timecourse.end} in ${(result.seconds * 1000).toFixed(0)} ms, ` +
            `${shown}${of} shown.`,
          "success",
        );
      } catch (error) {
        this.plot.hidden = true;
        this.legend.replaceChildren();
        this.show(`The simulation failed: ${error.message}`, "error");
      } finally {
        this.button.disabled = false;
      }
    }

    /**
     * Draw a result with its legend.
     *
     * @param {object} result The result of the simulation.
     * @param {{end: number}} timecourse What was integrated.
     */
    draw(result, timecourse) {
      const series = seriesOf(result);
      const range = rangeOf(result, series);
      this.plot.hidden = false;
      this.chart.show(result, {
        series,
        range: { start: 0, end: timecourse.end },
        maximum: range.maximum,
        minimum: range.minimum,
        labels: labelsOf(result, series),
      });
      this.legend.replaceChildren(
        ...series.map((entry) => {
          const item = document.createElement("span");
          item.className = "converter__legend-item";
          const swatch = document.createElement("span");
          swatch.className = "converter__swatch";
          swatch.style.background = entry.color;
          item.append(swatch, document.createTextNode(entry.label));
          return item;
        }),
      );
    }
  }

  window.sbml2cellmlSimulate = { Simulator };
})();
