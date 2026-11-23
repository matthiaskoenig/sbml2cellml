/* The timecourse chart of the pages which simulate in the browser.
 *
 * `window.sbml2cellmlChart` holds the chart of a canvas and the helpers both
 * pages use: the interactive simulation of the roundtrip example
 * (`repressilator.js`) and the simulation of the online converter
 * (`simulate.js`). The chart draws a grid with round ticks, the labels of
 * its axes and one line per series in the colors it is given, in the colors
 * of the theme and for the pixel ratio of the display.
 */

(() => {
  "use strict";

  /**
   * A color of the theme, which follows the light and the dark palette.
   *
   * @param {string} name The custom property of the color.
   * @param {string} fallback The color when the property is not set.
   * @returns {string} The color.
   */
  function themeColor(name, fallback) {
    const value = getComputedStyle(document.body).getPropertyValue(name);
    return value.trim() || fallback;
  }

  /**
   * A step of an axis which is a round number.
   *
   * @param {number} range The range of the axis.
   * @param {number} count The number of ticks it is divided into.
   * @returns {number} The step, 1, 2, 2.5 or 5 times a power of ten.
   */
  function niceStep(range, count) {
    const raw = range / count;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    for (const factor of [1, 2, 2.5, 5]) {
      if (raw <= factor * magnitude) {
        return factor * magnitude;
      }
    }
    return 10 * magnitude;
  }

  /**
   * A value of an axis as text, with as few digits as the step needs.
   *
   * @param {number} value The value of the tick.
   * @param {number} step The step of the axis.
   * @returns {string} The label.
   */
  function tickLabel(value, step) {
    if (step >= 1) {
      return value.toFixed(0);
    }
    if (step >= 0.01) {
      return value.toFixed(step >= 0.1 ? 1 : 2);
    }
    return value.toExponential(1);
  }

  /** The colors of the series of a plot, the palette of the pages. */
  const COLORS = [
    "#4e79a7",
    "#f28e2b",
    "#59a14f",
    "#e15759",
    "#b07aa1",
    "#76b7b2",
    "#edc948",
    "#ff9da7",
  ];

  /** Every chart of the page, which a change of the palette redraws. */
  const charts = new Set();

  // the theme of the page is the `data-md-color-scheme` of the body, and a
  // canvas keeps what was drawn with the colors of the palette before it,
  // so every chart is drawn again when the visitor switches the palette
  new MutationObserver(() => {
    for (const chart of charts) {
      chart.draw();
    }
  }).observe(document.body, {
    attributeFilter: ["data-md-color-scheme"],
  });

  /** The timecourse of a simulation on a canvas. */
  class Chart {
    /**
     * @param {HTMLCanvasElement} canvas The canvas of the plot.
     * @param {{x: string, y: string}} [labels] The labels of the axes.
     */
    constructor(canvas, labels = { x: "time", y: "value" }) {
      this.canvas = canvas;
      this.labels = labels;
      this.result = null;
      this.series = [];
      this.range = { start: 0, end: 1 };
      this.maximum = 1;
      this.minimum = 0;
      new ResizeObserver(() => this.draw()).observe(canvas);
      charts.add(this);
    }

    /**
     * Show a result.
     *
     * @param {{time: number[], series: Object<string, number[]>}} result The
     *   result of a simulation.
     * @param {object} options What to draw of it.
     * @param {Array<{id: string, label: string, color: string}>} options.series
     *   The series of the plot, in the order of the legend.
     * @param {{start: number, end: number}} options.range The range of the
     *   variable of integration.
     * @param {number} options.maximum The largest value of the axis, which
     *   two plots may share.
     * @param {number} [options.minimum] The smallest value of the axis, 0 by
     *   default.
     * @param {{x: string, y: string}} [options.labels] The labels of the
     *   axes, the ones of the constructor by default.
     */
    show(result, options) {
      this.result = result;
      this.series = options.series;
      this.range = options.range;
      this.maximum = options.maximum;
      this.minimum = options.minimum ?? 0;
      if (options.labels) {
        this.labels = options.labels;
      }
      this.draw();
    }

    /** Draw the result, nothing when there is none yet. */
    draw() {
      const canvas = this.canvas;
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (width === 0 || height === 0) {
        return;
      }
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      const context = canvas.getContext("2d");
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      if (this.result === null) {
        return;
      }
      const text = themeColor("--md-default-fg-color--light", "#666");
      const line = themeColor("--md-default-fg-color--lightest", "#ddd");
      const left = 52;
      const bottom = height - 32;
      const top = 10;
      const right = width - 12;
      const span = this.range.end - this.range.start || 1;
      const height_ = this.maximum - this.minimum || 1;
      const scaleX = (value) =>
        left + ((value - this.range.start) / span) * (right - left);
      const scaleY = (value) =>
        bottom - ((value - this.minimum) / height_) * (bottom - top);
      context.font =
        "11px -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif";
      context.strokeStyle = line;
      context.fillStyle = text;
      context.lineWidth = 1;
      // the grid with the labels of its round ticks
      const stepY = niceStep(height_, 4);
      context.textAlign = "right";
      context.textBaseline = "middle";
      const first = Math.ceil(this.minimum / stepY) * stepY;
      for (let value = first; value <= this.maximum + 1e-9; value += stepY) {
        const y = Math.round(scaleY(value)) + 0.5;
        context.beginPath();
        context.moveTo(left, y);
        context.lineTo(right, y);
        context.stroke();
        context.fillText(tickLabel(value, stepY), left - 6, y);
      }
      const stepX = niceStep(span, 6);
      context.textBaseline = "top";
      for (
        let value = this.range.start;
        value <= this.range.end + 1e-9;
        value += stepX
      ) {
        const x = Math.round(scaleX(value)) + 0.5;
        context.beginPath();
        context.moveTo(x, top);
        context.lineTo(x, bottom);
        context.stroke();
        // the first and the last label are kept inside the plot
        context.textAlign =
          value === this.range.start
            ? "left"
            : value + stepX > this.range.end
              ? "right"
              : "center";
        context.fillText(tickLabel(value, stepX), x, bottom + 6);
      }
      // the labels of the axes
      context.textAlign = "center";
      context.fillText(this.labels.x, (left + right) / 2, bottom + 19);
      context.save();
      context.translate(13, (top + bottom) / 2);
      context.rotate(-Math.PI / 2);
      context.textBaseline = "middle";
      context.fillText(this.labels.y, 0, 0);
      context.restore();
      // the timecourse of every series
      context.lineWidth = 1.6;
      context.lineJoin = "round";
      for (const series of this.series) {
        const values = this.result.series[series.id];
        if (values === undefined) {
          continue;
        }
        context.strokeStyle = series.color;
        context.beginPath();
        for (let index = 0; index < values.length; index += 1) {
          const x = scaleX(this.result.time[index]);
          const y = scaleY(values[index]);
          if (index === 0) {
            context.moveTo(x, y);
          } else {
            context.lineTo(x, y);
          }
        }
        context.stroke();
      }
    }
  }

  window.sbml2cellmlChart = { COLORS, Chart, niceStep, themeColor, tickLabel };
})();
