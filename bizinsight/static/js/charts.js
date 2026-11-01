/* BizInsight 360 chart helpers on top of Chart.js.
 * Colours are read from CSS tokens at build time, so every chart is rebuilt
 * when the theme changes and always matches the current light/dark palette. */
(function () {
  const builders = [];
  const charts = {};

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();
  const series = (i) => css("series-" + ((i % 6) + 1));

  function inr(v) {
    if (v === null || v === undefined || isNaN(v)) return "-";
    const sign = v < 0 ? "-" : "";
    const a = Math.abs(v);
    if (a >= 1e7) return sign + "₹" + (a / 1e7).toFixed(2) + " Cr";
    if (a >= 1e5) return sign + "₹" + (a / 1e5).toFixed(2) + " L";
    if (a >= 1e3) return sign + "₹" + (a / 1e3).toFixed(1) + "K";
    return sign + "₹" + a.toFixed(0);
  }
  const pct = (v) => (v === null || v === undefined ? "-" : (v * 100).toFixed(1) + "%");
  const num = (v) => (v === null || v === undefined ? "-" : Math.round(v).toLocaleString("en-IN"));
  const fmt = { inr, pct, num };

  function axis(format, extra) {
    return Object.assign({
      grid: { color: css("grid"), drawTicks: false },
      border: { color: css("axis") },
      ticks: { color: css("muted"), padding: 6, callback: function (v) {
        return format ? fmt[format](v) : this.getLabelForValue(v);
      } },
    }, extra || {});
  }

  function categoryAxis(extra) {
    extra = extra || {};
    return Object.assign({
      grid: { display: false },
      border: { color: css("axis") },
    }, extra, {
      ticks: Object.assign({ color: css("muted"), padding: 6, autoSkip: true, maxRotation: 0 }, extra.ticks),
    });
  }

  function baseOptions(format, opts) {
    opts = opts || {};
    const horizontal = !!opts.horizontal;
    const valueAxis = axis(format, opts.valueAxis);
    // Horizontal bars list every category label; vertical axes may thin them out
    const catAxis = categoryAxis(Object.assign({}, opts.catAxis,
      horizontal ? { ticks: Object.assign({ autoSkip: false }, (opts.catAxis || {}).ticks) } : {}));
    if (opts.stacked) { valueAxis.stacked = true; catAxis.stacked = true; }
    return {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: horizontal ? "y" : "x",
      interaction: { mode: opts.single ? "nearest" : "index", intersect: !!opts.single, axis: horizontal ? "y" : "x" },
      animation: matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 300 },
      plugins: {
        legend: {
          display: !!opts.legend,
          position: "top", align: "start",
          labels: { color: css("ink-2"), usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10,
            // Line series with an area wash: key the legend on the line colour, not the pale fill
            generateLabels: (chart) => Chart.defaults.plugins.legend.labels.generateLabels(chart).map((l) =>
              chart.config.type === "line" ? Object.assign(l, (({ borderColor: c }) => ({ fillStyle: c, strokeStyle: c }))(chart.data.datasets[l.datasetIndex])) : l) },
        },
        tooltip: {
          backgroundColor: css("surface"), titleColor: css("ink"), bodyColor: css("ink-2"),
          borderColor: css("axis"), borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true,
          callbacks: {
            label: (ctx) => {
              // Floating bars (waterfall) carry [start, end]; show the step size
              const value = Array.isArray(ctx.raw) ? ctx.raw[1] - ctx.raw[0] : (horizontal ? ctx.parsed.x : ctx.parsed.y);
              const f = (opts.formats && opts.formats[ctx.datasetIndex]) || format;
              return " " + (ctx.dataset.label ? ctx.dataset.label + ": " : "") + (f ? fmt[f](value) : value);
            },
          },
        },
      },
      scales: horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis },
    };
  }

  function barDataset(label, data, color, extra) {
    return Object.assign({
      label, data,
      backgroundColor: color,
      borderRadius: 4, borderSkipped: "start", maxBarThickness: 24,
      categoryPercentage: 0.75, barPercentage: 0.9,
    }, extra || {});
  }

  function lineDataset(label, data, color, extra) {
    return Object.assign({
      label, data, borderColor: color, backgroundColor: color, borderWidth: 2, tension: 0.25,
      pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2, pointHoverBorderColor: css("surface"),
      borderCapStyle: "round", borderJoinStyle: "round",
    }, extra || {});
  }

  function register(id, build) {
    const el = document.getElementById(id);
    if (!el) return;
    const existing = builders.findIndex((b) => b.id === id);
    if (existing >= 0) builders.splice(existing, 1);
    builders.push({ id, build });
    draw(id, build);
  }

  function draw(id, build) {
    const el = document.getElementById(id);
    if (charts[id]) charts[id].destroy();
    Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
    Chart.defaults.font.size = 11.5;
    Chart.defaults.color = css("ink-2");
    charts[id] = new Chart(el, build());
  }

  function redraw() { builders.forEach((b) => draw(b.id, b.build)); }

  /* ---- public chart shapes ---- */

  // Single series bar: one colour for every bar (nominal categories carry no ramp)
  function bar(id, labels, values, format, opts) {
    opts = opts || {};
    register(id, () => ({
      type: "bar",
      data: { labels, datasets: [barDataset(opts.label || "", values,
        opts.colorFn ? values.map(opts.colorFn) : (opts.color ? css(opts.color) : series(0)))] },
      options: baseOptions(format, Object.assign({ single: true }, opts)),
    }));
  }

  // Several series as grouped (or stacked) bars; colour follows series order
  function bars(id, labels, sets, format, opts) {
    opts = opts || {};
    register(id, () => ({
      type: "bar",
      data: { labels, datasets: sets.map((s, i) => barDataset(s.label, s.data, css(s.color || "series-" + (i + 1)),
        opts.stacked ? { borderRadius: 2, borderWidth: { top: 2 }, borderColor: css("surface"), borderSkipped: "start" } : {})) },
      options: baseOptions(format, Object.assign({ legend: sets.length > 1 }, opts)),
    }));
  }

  function line(id, labels, sets, format, opts) {
    opts = opts || {};
    register(id, () => ({
      type: "line",
      data: {
        labels,
        datasets: sets.map((s, i) => {
          const color = css(s.color || "series-" + (i + 1));
          return lineDataset(s.label, s.data, color, Object.assign(
            { pointBorderColor: css("surface"), pointBorderWidth: 2 },
            s.fill ? { fill: "origin", backgroundColor: color + "1a" } : {},
            s.muted ? { borderColor: css("muted"), borderWidth: 1.5, backgroundColor: css("muted") } : {},
            s.extra || {}));
        }),
      },
      options: baseOptions(format, Object.assign({ legend: sets.length > 1 }, opts)),
    }));
  }

  // Part-to-whole at a glance only (<= 6 slices)
  function donut(id, labels, values, format) {
    register(id, () => ({
      type: "doughnut",
      data: { labels, datasets: [{ data: values, backgroundColor: labels.map((_, i) => series(i)),
        borderColor: css("surface"), borderWidth: 2, hoverOffset: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "68%",
        plugins: {
          legend: { position: "right", labels: { color: css("ink-2"), usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10 } },
          tooltip: {
            backgroundColor: css("surface"), titleColor: css("ink"), bodyColor: css("ink-2"),
            borderColor: css("axis"), borderWidth: 1, padding: 10,
            callbacks: { label: (ctx) => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              return " " + ctx.label + ": " + fmt[format](ctx.parsed) + " (" + pct(ctx.parsed / total) + ")";
            } },
          },
        },
      },
    }));
  }

  /* ---- theme ---- */
  function applyTheme(theme) {
    const root = document.documentElement;
    if (theme) root.setAttribute("data-theme", theme); else root.removeAttribute("data-theme");
    const dark = theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.setAttribute("data-bs-theme", dark ? "dark" : "light");
    const icon = document.getElementById("themeIcon");
    if (icon) icon.className = dark ? "bi bi-sun" : "bi bi-moon-stars";
  }
  function toggleTheme() {
    const dark = document.documentElement.getAttribute("data-bs-theme") === "dark";
    const next = dark ? "light" : "dark";
    try { localStorage.setItem("biz-theme", next); } catch (e) { /* storage blocked */ }
    applyTheme(next);
    redraw();
  }
  let saved = null;
  try { saved = localStorage.getItem("biz-theme"); } catch (e) { /* storage blocked */ }
  applyTheme(saved);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    let s = null;
    try { s = localStorage.getItem("biz-theme"); } catch (e) { /* ignore */ }
    if (!s) { applyTheme(null); redraw(); }
  });

  window.BIZ = { bar, bars, line, donut, css, series, fmt, toggleTheme, redraw };
})();
