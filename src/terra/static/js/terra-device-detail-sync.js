/**
 * Device detail — immediate inventory enrich + cellular history (async job + progress bar).
 */
(function () {
  var STORAGE_PREFIX = "terra_device_sync_job:";

  function storageKey(deviceId) {
    return STORAGE_PREFIX + deviceId;
  }

  function humanPhase(phase) {
    var m = {
      queued: "Queued",
      connecting: "Connecting to Manager",
      inventory: "Refreshing inventory",
      enriching: "Fetching interfaces & cellular",
      saving: "Saving to TERRA",
      cellular: "Cellular RF history",
      done: "Complete",
      failed: "Failed",
      cancelled: "Cancelled",
      running: "Working",
    };
    return m[String(phase || "")] || String(phase || "Progress");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  var root = document.getElementById("terra-device-live-root");
  if (!root) {
    return;
  }

  var deviceId = root.getAttribute("data-device-id");
  var syncUrl = root.getAttribute("data-sync-url");
  var syncBtn = document.getElementById("terra-sync-now");
  var liveBtn = document.getElementById("terra-live-toggle");
  var liveStatus = document.getElementById("terra-live-status");
  var progressRoot = document.getElementById("terra-sync-progress");
  var progressFill = document.getElementById("terra-sync-progress-fill");
  var progressPct = document.getElementById("terra-sync-progress-pct");
  var progressBar = progressRoot ? progressRoot.querySelector(".terra-live-progress-bar") : null;
  var statusText = document.getElementById("terra-sync-status-text");

  if (!deviceId || !syncUrl || !syncBtn) {
    return;
  }

  var pollTimer = null;
  var activeJobId = null;

  function setUiBusy(busy) {
    syncBtn.disabled = !!busy;
    syncBtn.setAttribute("aria-busy", busy ? "true" : "false");
    if (liveBtn) {
      liveBtn.disabled = !!busy;
    }
  }

  function showProgress(show) {
    if (progressRoot) {
      progressRoot.hidden = !show;
    }
  }

  function applyJob(job) {
    var pct = typeof job.percent === "number" ? job.percent : parseInt(String(job.percent || 0), 10) || 0;
    pct = Math.min(100, Math.max(0, pct));
    if (progressFill) {
      progressFill.style.width = pct + "%";
    }
    if (progressPct) {
      progressPct.textContent = pct + "%";
    }
    if (progressBar) {
      progressBar.setAttribute("aria-valuenow", String(pct));
    }
    var msg = humanPhase(job.phase) + " — " + (job.message || "");
    if (statusText) {
      statusText.textContent = msg;
    }
    if (liveStatus && String(job.status || "") !== "done") {
      liveStatus.textContent = "Sync in progress…";
    }
  }

  function showInlineError(msg) {
    stopPoll();
    activeJobId = null;
    clearStoredJob();
    setUiBusy(false);
    showProgress(true);
    if (progressFill) {
      progressFill.style.width = "0%";
    }
    if (progressPct) {
      progressPct.textContent = "";
    }
    if (progressBar) {
      progressBar.setAttribute("aria-valuenow", "0");
    }
    if (statusText) {
      statusText.textContent = msg;
      statusText.classList.add("terra-device-sync-status--error");
    }
    if (liveStatus) {
      liveStatus.textContent = "Sync failed";
    }
  }

  function clearInlineError() {
    if (statusText) {
      statusText.classList.remove("terra-device-sync-status--error");
    }
  }
    try {
      window.sessionStorage.removeItem(storageKey(deviceId));
    } catch (_e) {}
  }

  function storeJob(jobId) {
    try {
      window.sessionStorage.setItem(storageKey(deviceId), jobId);
    } catch (_e) {}
  }

  function readStoredJob() {
    try {
      return window.sessionStorage.getItem(storageKey(deviceId));
    } catch (_e) {
      return null;
    }
  }

  function stopPoll() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function finishJob(job) {
    stopPoll();
    activeJobId = null;
    clearStoredJob();
    var st = String(job.status || "");
    if (st === "done") {
      clearInlineError();
      applyJob(job);
      if (liveStatus) {
        liveStatus.textContent = "Sync complete — reloading…";
      }
      window.setTimeout(function () {
        window.location.reload();
      }, 400);
      return;
    }
    setUiBusy(false);
    showProgress(false);
    if (liveStatus) {
      liveStatus.textContent = "";
    }
    if (st === "failed") {
      showInlineError(job.message || job.error_detail || "Device sync failed.");
    }
  }

  function pollJob(jobId) {
    fetch("/api/v1/me/sync-sdwan-jobs/" + encodeURIComponent(jobId), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) {
        if (!r.ok) {
          throw new Error("HTTP " + r.status);
        }
        return r.json();
      })
      .then(function (job) {
        applyJob(job);
        var st = String(job.status || "");
        if (st === "done" || st === "failed" || st === "cancelled") {
          finishJob(job);
        }
      })
      .catch(function (e) {
        stopPoll();
        showInlineError("Could not read sync status: " + String(e));
      });
  }

  function attachPolling(jobId) {
    activeJobId = jobId;
    storeJob(jobId);
    clearInlineError();
    setUiBusy(true);
    showProgress(true);
    applyJob({ phase: "queued", percent: 0, message: "Queued…", status: "queued" });
    pollJob(jobId);
    stopPoll();
    pollTimer = window.setInterval(function () {
      pollJob(jobId);
    }, 900);
  }

  syncBtn.addEventListener("click", function () {
    if (syncBtn.disabled) {
      return;
    }
    clearInlineError();
    setUiBusy(true);
    showProgress(true);
    applyJob({ phase: "queued", percent: 0, message: "Starting sync…", status: "queued" });
    fetch(syncUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) {
        if (!r.ok) {
          return r.json().then(function (body) {
            var detail = body && body.detail;
            throw new Error(typeof detail === "string" ? detail : "HTTP " + r.status);
          });
        }
        return r.json();
      })
      .then(function (body) {
        if (!body || !body.job_id) {
          throw new Error("Missing job id");
        }
        attachPolling(body.job_id);
      })
      .catch(function (e) {
        showInlineError("Could not start sync: " + String(e.message || e));
      });
  });

  var resumed = readStoredJob();
  if (resumed) {
    attachPolling(resumed);
  }
})();
