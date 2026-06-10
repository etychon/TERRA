/**
 * SD-WAN Administration: relative "last inventory sync" labels; per-row async Sync now with inline progress.
 * Job id is persisted in sessionStorage so inventory sync continues to run server-side when navigating away;
 * returning to this page resumes status polling until the job reaches a terminal state.
 */
(function () {
  var JOB_STORAGE_PREFIX = "terra_sdwan_sync_job:";

  function jobStorageKey(instanceId) {
    return JOB_STORAGE_PREFIX + instanceId;
  }

  function persistSyncJob(instanceId, jobId) {
    try {
      window.sessionStorage.setItem(
        jobStorageKey(instanceId),
        JSON.stringify({ jobId: jobId, savedAt: Date.now() }),
      );
    } catch (_e) {}
  }

  function readSyncJob(instanceId) {
    try {
      var raw = window.sessionStorage.getItem(jobStorageKey(instanceId));
      if (!raw) {
        return null;
      }
      var o = JSON.parse(raw);
      if (o && typeof o.jobId === "string" && o.jobId) {
        return o.jobId;
      }
    } catch (_e) {}
    return null;
  }

  function clearSyncJob(instanceId) {
    try {
      window.sessionStorage.removeItem(jobStorageKey(instanceId));
    } catch (_e) {}
  }

  function parseUtcIso(iso) {
    var s = String(iso || "").trim();
    if (!s) {
      return null;
    }
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ+]|[+-]\d{2}:?\d{2}$/.test(s)) {
      s = s.replace(" ", "T") + "Z";
    }
    var d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function formatRelativePast(d) {
    var ms = Date.now() - d.getTime();
    var sec = Math.max(0, Math.floor(ms / 1000));
    if (sec < 10) {
      return "just now";
    }
    if (sec < 60) {
      return sec === 1 ? "1 second ago" : sec + " seconds ago";
    }
    var min = Math.floor(sec / 60);
    if (min < 60) {
      return min === 1 ? "1 minute ago" : min + " minutes ago";
    }
    var hr = Math.floor(min / 60);
    if (hr < 48) {
      return hr === 1 ? "1 hour ago" : hr + " hours ago";
    }
    var day = Math.floor(hr / 24);
    if (day < 60) {
      return day === 1 ? "1 day ago" : day + " days ago";
    }
    var mo = Math.floor(day / 30);
    return mo === 1 ? "about 1 month ago" : "about " + mo + " months ago";
  }

  function updateEl(el) {
    var iso = el.getAttribute("data-utc");
    var d = parseUtcIso(iso);
    if (!d) {
      el.textContent = "Never";
      return;
    }
    el.textContent = formatRelativePast(d);
  }

  function refreshAll() {
    document.querySelectorAll("[data-terra-relative-sync]").forEach(updateEl);
  }

  function detailFromBody(data) {
    var d = data && data.detail;
    if (typeof d === "string") {
      return d;
    }
    if (Array.isArray(d) && d[0] && typeof d[0].msg === "string") {
      return d[0].msg;
    }
    return "";
  }

  function humanPhase(phase) {
    var m = {
      queued: "Queued",
      connecting: "Connecting to Manager",
      connected: "Connected",
      inventory: "Downloading device inventory",
      enriching: "Enriching device details",
      saving: "Saving devices to database",
      finishing: "Finalizing",
      complete: "Complete",
      done: "Complete",
      failed: "Failed",
      cancelled: "Cancelled",
      running: "Working",
    };
    return m[String(phase || "")] || String(phase || "Progress");
  }

  /**
   * @param {HTMLElement} panelHost — ``tr.terra-sdwan-sync-inline-row`` (sibling after manager row)
   */
  function bindInlineSyncUi(panelHost) {
    var panel = panelHost.querySelector(".terra-sdwan-sync-inline-panel");
    if (!panel) {
      return null;
    }
    var fill = panel.querySelector(".terra-sdwan-sync-fill");
    var status = panel.querySelector(".terra-sdwan-sync-status");
    var sub = panel.querySelector(".terra-sdwan-sync-sub");
    var closeBtn = panel.querySelector(".terra-sdwan-sync-close");
    var cancelBtn = panel.querySelector(".terra-sdwan-sync-cancel");
    var nameEl = panel.querySelector(".terra-sdwan-sync-inline-for");
    return { panelHost, panel, fill, status, sub, closeBtn, cancelBtn, nameEl };
  }

  function applyJobToInlineUi(ui, job) {
    if (!ui || !job) {
      return;
    }
    var pct = typeof job.percent === "number" ? job.percent : parseInt(String(job.percent || 0), 10) || 0;
    if (ui.fill) {
      ui.fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
    }
    if (ui.status) {
      ui.status.textContent = humanPhase(job.phase) + " — " + (job.message || "");
    }
    if (ui.sub) {
      var t = "Progress: " + pct + "%";
      if (job.status === "done" && job.rows_touched != null) {
        t += " · Rows updated: " + job.rows_touched;
      }
      if (job.errors && job.error_detail) {
        t += " · " + job.error_detail;
      }
      ui.sub.textContent = t;
    }
    var st = String(job.status || "");
    var terminal = st === "done" || st === "failed" || st === "cancelled";
    if (ui.closeBtn) {
      ui.closeBtn.disabled = !terminal;
    }
    if (ui.cancelBtn) {
      ui.cancelBtn.disabled = terminal || st === "";
    }
  }

  /**
   * Poll job status until terminal; persists job id until then so navigation away does not lose track.
   */
  function attachSyncJobPolling(instanceId, jobId, ui, btn, row, inlineRow, btnDefaultText) {
    if (inlineRow.getAttribute("data-terra-sync-active-job") === jobId) {
      return;
    }
    inlineRow.setAttribute("data-terra-sync-active-job", jobId);
    var poll = null;
    var finished = false;

    function stopPoll() {
      if (poll) {
        window.clearInterval(poll);
      }
      poll = null;
    }

    function cleanupUi() {
      stopPoll();
      inlineRow.removeAttribute("data-terra-sync-active-job");
      if (row) {
        row.classList.remove("terra-sdwan-row--syncing");
      }
      btn.disabled = false;
      btn.textContent = btnDefaultText;
    }

    function hideInline() {
      inlineRow.setAttribute("hidden", "hidden");
    }

    function onTerminal(j) {
      finished = true;
      stopPoll();
      inlineRow.removeAttribute("data-terra-sync-active-job");
      clearSyncJob(instanceId);
      if (ui.closeBtn) {
        ui.closeBtn.disabled = false;
        ui.closeBtn.focus();
      }
      if (j && j.status === "done" && j.errors && j.errors > 0) {
        var reason = typeof j.error_detail === "string" && j.error_detail.trim() ? j.error_detail.trim() : "";
        window.alert(
          reason
            ? "Sync finished with errors.\n\n" + reason
            : "Sync finished with errors (see Details column after Close).",
        );
      }
    }

    if (ui.closeBtn) {
      ui.closeBtn.onclick = function () {
        hideInline();
        cleanupUi();
        window.location.reload();
      };
    }

    if (ui.cancelBtn) {
      ui.cancelBtn.onclick = async function () {
        if (!jobId || finished) {
          return;
        }
        ui.cancelBtn.disabled = true;
        try {
          var cr = await fetch("/api/v1/me/sync-sdwan-jobs/" + encodeURIComponent(jobId) + "/cancel", {
            method: "POST",
            credentials: "same-origin",
          });
          if (!cr.ok) {
            var msg = "";
            try {
              var b = await cr.json();
              msg = detailFromBody(b) || "";
            } catch (_e) {
              msg = "";
            }
            window.alert(msg || "Cancel request failed (" + cr.status + ")");
            ui.cancelBtn.disabled = false;
            return;
          }
          if (ui.sub) {
            ui.sub.textContent = "Cancellation requested — stopping after the current step…";
          }
        } catch (_e) {
          window.alert("Network error requesting cancel.");
          ui.cancelBtn.disabled = false;
        }
      };
    }

    var runPoll = async function () {
      if (finished) {
        return;
      }
      var r = await fetch("/api/v1/me/sync-sdwan-jobs/" + encodeURIComponent(jobId), {
        credentials: "same-origin",
      });
      if (r.status === 404) {
        finished = true;
        stopPoll();
        inlineRow.removeAttribute("data-terra-sync-active-job");
        clearSyncJob(instanceId);
        if (ui.status) {
          ui.status.textContent = "Job status no longer available";
        }
        if (ui.sub) {
          ui.sub.textContent =
            "The server may have restarted or the job record expired. If sync was still running it may finish in the background — refresh the page to see updated “Last inventory sync”.";
        }
        if (ui.closeBtn) {
          ui.closeBtn.disabled = false;
        }
        if (ui.cancelBtn) {
          ui.cancelBtn.disabled = true;
        }
        if (row) {
          row.classList.remove("terra-sdwan-row--syncing");
        }
        btn.disabled = false;
        btn.textContent = btnDefaultText;
        return;
      }
      if (!r.ok) {
        return;
      }
      var j = await r.json();
      applyJobToInlineUi(ui, j);
      if (j.status === "done" || j.status === "failed" || j.status === "cancelled") {
        onTerminal(j);
      }
    };

    runPoll();
    if (!finished) {
      poll = window.setInterval(runPoll, 500);
    }
  }

  function resumePendingSyncForRow(instanceId) {
    var jobId = readSyncJob(instanceId);
    if (!jobId) {
      return;
    }
    var inlineRow = document.querySelector('[data-terra-sync-row-for="' + instanceId + '"]');
    var btn = document.querySelector('.terra-sdwan-sync-one[data-instance-id="' + instanceId + '"]');
    if (!inlineRow || !btn) {
      clearSyncJob(instanceId);
      return;
    }
    var ui = bindInlineSyncUi(inlineRow);
    if (!ui) {
      clearSyncJob(instanceId);
      return;
    }
    var row = btn.closest("tr");
    var displayName = (btn.getAttribute("data-instance-name") || "").trim();
    if (ui.nameEl) {
      ui.nameEl.textContent = displayName ? "(" + displayName + ")" : "";
    }
    inlineRow.removeAttribute("hidden");
    if (row) {
      row.classList.add("terra-sdwan-row--syncing");
    }
    var origLabel = (btn.textContent || "").trim() || "Sync now";
    btn.disabled = true;
    btn.textContent = "Syncing…";
    if (ui.fill) {
      ui.fill.style.width = "0%";
    }
    if (ui.status) {
      ui.status.textContent = "Resuming status…";
    }
    if (ui.sub) {
      ui.sub.textContent = "Sync continues on the server while you use other pages.";
    }
    if (ui.closeBtn) {
      ui.closeBtn.disabled = true;
    }
    if (ui.cancelBtn) {
      ui.cancelBtn.disabled = false;
    }
    attachSyncJobPolling(instanceId, jobId, ui, btn, row, inlineRow, origLabel);
  }

  document.addEventListener("DOMContentLoaded", function () {
    refreshAll();
    window.setInterval(refreshAll, 30000);

    document.querySelectorAll("[data-terra-sync-row-for]").forEach(function (el) {
      var id = el.getAttribute("data-terra-sync-row-for");
      if (id) {
        resumePendingSyncForRow(id);
      }
    });

    window.addEventListener("pageshow", function (ev) {
      if (!ev.persisted) {
        return;
      }
      document.querySelectorAll("[data-terra-sync-row-for]").forEach(function (el) {
        var id = el.getAttribute("data-terra-sync-row-for");
        if (id) {
          resumePendingSyncForRow(id);
        }
      });
    });

    document.querySelectorAll(".terra-sdwan-sync-one").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        var id = btn.getAttribute("data-instance-id");
        if (!id) {
          return;
        }
        var displayName = (btn.getAttribute("data-instance-name") || "").trim();
        var row = btn.closest("tr");
        var inlineRow = document.querySelector('[data-terra-sync-row-for="' + id + '"]');
        if (!inlineRow) {
          window.alert("Sync panel not found for this row.");
          return;
        }
        var ui = bindInlineSyncUi(inlineRow);
        if (!ui) {
          return;
        }
        if (ui.nameEl) {
          ui.nameEl.textContent = displayName ? "(" + displayName + ")" : "";
        }

        btn.disabled = true;
        var orig = btn.textContent;
        btn.textContent = "Syncing…";
        if (row) {
          row.classList.add("terra-sdwan-row--syncing");
        }
        inlineRow.removeAttribute("hidden");
        if (ui.fill) {
          ui.fill.style.width = "0%";
        }
        if (ui.status) {
          ui.status.textContent = "Starting…";
        }
        if (ui.sub) {
          ui.sub.textContent = "";
        }
        if (ui.closeBtn) {
          ui.closeBtn.disabled = true;
        }
        if (ui.cancelBtn) {
          ui.cancelBtn.disabled = true;
        }

        try {
          var start = await fetch("/api/v1/me/sync-sdwan-devices/" + encodeURIComponent(id) + "/async", {
            method: "POST",
            credentials: "same-origin",
          });
          var body = {};
          try {
            body = await start.json();
          } catch (_e) {
            body = {};
          }
          if (!start.ok) {
            window.alert(detailFromBody(body) || "Could not start sync (" + start.status + ")");
            inlineRow.setAttribute("hidden", "hidden");
            if (row) {
              row.classList.remove("terra-sdwan-row--syncing");
            }
            btn.disabled = false;
            btn.textContent = orig;
            return;
          }
          var jobId = body.job_id;
          if (!jobId) {
            window.alert("Server did not return a job id.");
            inlineRow.setAttribute("hidden", "hidden");
            if (row) {
              row.classList.remove("terra-sdwan-row--syncing");
            }
            btn.disabled = false;
            btn.textContent = orig;
            return;
          }

          persistSyncJob(id, jobId);

          if (ui.cancelBtn) {
            ui.cancelBtn.disabled = false;
          }

          attachSyncJobPolling(id, jobId, ui, btn, row, inlineRow, orig);
        } catch (_e) {
          window.alert("Network error during sync.");
          inlineRow.setAttribute("hidden", "hidden");
          if (row) {
            row.classList.remove("terra-sdwan-row--syncing");
          }
          btn.disabled = false;
          btn.textContent = orig;
        }
      });
    });
  });
})();
