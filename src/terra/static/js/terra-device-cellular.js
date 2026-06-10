/**
 * Cellular EIOLTE history chart (VictoriaMetrics via /api/v1/me/devices/{id}/cellular/history).
 */
(function () {
  const root = document.getElementById("terra-cellular-history-root");
  if (!root || typeof echarts === "undefined") {
    return;
  }
  const deviceId = root.getAttribute("data-device-id");
  const hasCellular = root.getAttribute("data-has-cellular") === "true";
  const chartEl = document.getElementById("terra-cellular-chart");
  const chartExpandedEl = document.getElementById("terra-cellular-chart-expanded");
  const statusEl = document.getElementById("terra-cellular-history-status");
  const overlay = document.getElementById("terra-cellular-chart-overlay");
  const expandBtn = document.getElementById("terra-cellular-expand-btn");
  const closeBtn = document.getElementById("terra-cellular-overlay-close");
  const metricRsrp = document.getElementById("terra-cellular-metric-rsrp");
  const metricRsrq = document.getElementById("terra-cellular-metric-rsrq");

  if (!deviceId || !chartEl) {
    return;
  }

  let rangeHours = 24;
  let lastPayload = null;
  let chartMain = null;
  let chartExpanded = null;
  let activeChart = null;

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  const colors = {
    line: [
      cssVar("--md-sys-color-primary", "#1a73b8"),
      cssVar("--md-sys-color-tertiary", "#0d7a6b"),
      cssVar("--md-sys-color-secondary", "#5c6bc0"),
      cssVar("--md-sys-color-error", "#b3261e"),
    ],
    text: cssVar("--md-sys-color-on-surface", "#1a1c1e"),
    muted: cssVar("--md-sys-color-on-surface-variant", "#5c5f62"),
    grid: cssVar("--md-sys-color-outline-variant", "#e0e2e5"),
  };

  function setStatus(msg) {
    if (statusEl) {
      statusEl.textContent = msg || "";
    }
  }

  function selectedMetrics() {
    const out = [];
    if (metricRsrp && metricRsrp.checked) {
      out.push("rsrp");
    }
    if (metricRsrq && metricRsrq.checked) {
      out.push("rsrq");
    }
    return out;
  }

  function buildSeries(payload) {
    const metrics = selectedMetrics();
    const series = [];
    let colorIx = 0;
    (payload.series || []).forEach(function (s) {
      if (metrics.indexOf(s.metric) < 0) {
        return;
      }
      const labelParts = [s.metric.toUpperCase()];
      if (s.slot) {
        labelParts.push("slot " + s.slot);
      }
      if (s.active_sim) {
        labelParts.push("SIM " + s.active_sim);
      }
      const data = [];
      for (let i = 0; i < (s.timestamps || []).length; i++) {
        data.push([s.timestamps[i] * 1000, s.values[i]]);
      }
      series.push({
        name: labelParts.join(" · ") + " (dBm)",
        type: "line",
        showSymbol: false,
        connectNulls: false,
        emphasis: { focus: "series" },
        lineStyle: { width: 2 },
        itemStyle: { color: colors.line[colorIx % colors.line.length] },
        data: data,
      });
      colorIx += 1;
    });
    return series;
  }

  function chartOption(payload) {
    const series = buildSeries(payload);
    return {
      animation: false,
      color: colors.line,
      textStyle: { color: colors.text },
      legend: {
        type: "scroll",
        bottom: 0,
        textStyle: { color: colors.muted },
      },
      grid: { left: 56, right: 24, top: 24, bottom: 72 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        valueFormatter: function (v) {
          return v == null ? "—" : v + " dBm";
        },
      },
      toolbox: {
        feature: {
          dataZoom: { yAxisIndex: "none" },
          restore: {},
        },
        right: 8,
      },
      brush: {
        toolbox: ["lineX", "clear"],
        xAxisIndex: 0,
      },
      xAxis: {
        type: "time",
        axisLabel: { color: colors.muted },
        axisLine: { lineStyle: { color: colors.grid } },
      },
      yAxis: {
        type: "value",
        name: "dBm",
        nameTextStyle: { color: colors.muted },
        axisLabel: { color: colors.muted },
        splitLine: { lineStyle: { color: colors.grid } },
      },
      dataZoom: [
        { type: "inside", xAxisIndex: 0 },
        { type: "slider", xAxisIndex: 0, height: 22, bottom: 36 },
      ],
      series: series,
    };
  }

  function renderChart(inst, payload) {
    if (!inst) {
      return;
    }
    inst.setOption(chartOption(payload), { notMerge: true });
    inst.resize();
  }

  function ensureChart(el, existing) {
    if (!el) {
      return existing;
    }
    if (existing) {
      return existing;
    }
    return echarts.init(el, null, { renderer: "canvas" });
  }

  function refreshCharts() {
    if (!lastPayload) {
      return;
    }
    renderChart(chartMain, lastPayload);
    if (chartExpanded && !overlay.hidden) {
      renderChart(chartExpanded, lastPayload);
    }
  }

  function fetchHistory() {
    const end = Math.floor(Date.now() / 1000);
    const start = end - rangeHours * 3600;
    const metrics = selectedMetrics().join(",");
    const url =
      "/api/v1/me/devices/" +
      encodeURIComponent(deviceId) +
      "/cellular/history?start=" +
      start +
      "&end=" +
      end +
      "&metrics=" +
      encodeURIComponent(metrics || "rsrp,rsrq");
    setStatus("Loading…");
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) {
          throw new Error("HTTP " + r.status);
        }
        return r.json();
      })
      .then(function (payload) {
        lastPayload = payload;
        if (!payload.series || !payload.series.length) {
          setStatus(payload.note || "No history samples yet.");
        } else {
          setStatus("");
        }
        chartMain = ensureChart(chartEl, chartMain);
        activeChart = chartMain;
        renderChart(chartMain, payload);
        if (!overlay.hidden && chartExpandedEl) {
          chartExpanded = ensureChart(chartExpandedEl, chartExpanded);
          renderChart(chartExpanded, payload);
        }
      })
      .catch(function () {
        setStatus("Could not load cellular history.");
      });
  }

  root.querySelectorAll("[data-terra-range-hours]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      rangeHours = parseInt(btn.getAttribute("data-terra-range-hours"), 10) || 24;
      root.querySelectorAll("[data-terra-range-hours]").forEach(function (b) {
        b.classList.toggle("terra-cellular-range--active", b === btn);
      });
      fetchHistory();
    });
  });

  if (metricRsrp) {
    metricRsrp.addEventListener("change", function () {
      if (!selectedMetrics().length) {
        metricRsrp.checked = true;
      }
      fetchHistory();
    });
  }
  if (metricRsrq) {
    metricRsrq.addEventListener("change", function () {
      if (!selectedMetrics().length) {
        metricRsrq.checked = true;
      }
      fetchHistory();
    });
  }

  if (expandBtn && overlay && chartExpandedEl) {
    expandBtn.addEventListener("click", function () {
      overlay.hidden = false;
      document.body.classList.add("terra-cellular-overlay-open");
      chartExpanded = ensureChart(chartExpandedEl, chartExpanded);
      activeChart = chartExpanded;
      if (lastPayload) {
        renderChart(chartExpanded, lastPayload);
      } else {
        fetchHistory();
      }
      setTimeout(function () {
        if (chartExpanded) {
          chartExpanded.resize();
        }
      }, 50);
    });
  }
  if (closeBtn && overlay) {
    closeBtn.addEventListener("click", function () {
      overlay.hidden = true;
      document.body.classList.remove("terra-cellular-overlay-open");
      activeChart = chartMain;
      if (chartMain) {
        chartMain.resize();
      }
    });
  }

  window.addEventListener("resize", function () {
    if (chartMain) {
      chartMain.resize();
    }
    if (chartExpanded && !overlay.hidden) {
      chartExpanded.resize();
    }
  });

  if (hasCellular) {
    fetchHistory();
  } else {
    setStatus("No cellular module detected in inventory.");
  }
})();
