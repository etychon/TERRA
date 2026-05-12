/**
 * SD-WAN Administration: relative "last inventory sync" labels; per-row async Sync now with inline progress.
 */
(function () {
  function parseUtcIso(iso) {
    let s = String(iso || "").trim();
    if (!s) {
      return null;
    }
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ+]|[+-]\d{2}:?\d{2}$/.test(s)) {
      s = s.replace(" ", "T") + "Z";
    }
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function formatRelativePast(d) {
    const ms = Date.now() - d.getTime();
    const sec = Math.max(0, Math.floor(ms / 1000));
    if (sec < 10) {
      return "just now";
    }
    if (sec < 60) {
      return sec === 1 ? "1 second ago" : `${sec} seconds ago`;
    }
    const min = Math.floor(sec / 60);
    if (min < 60) {
      return min === 1 ? "1 minute ago" : `${min} minutes ago`;
    }
    const hr = Math.floor(min / 60);
    if (hr < 48) {
      return hr === 1 ? "1 hour ago" : `${hr} hours ago`;
    }
    const day = Math.floor(hr / 24);
    if (day < 60) {
      return day === 1 ? "1 day ago" : `${day} days ago`;
    }
    const mo = Math.floor(day / 30);
    return mo === 1 ? "about 1 month ago" : `about ${mo} months ago`;
  }

  function updateEl(el) {
    const iso = el.getAttribute("data-utc");
    const d = parseUtcIso(iso);
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
    const d = data && data.detail;
    if (typeof d === "string") {
      return d;
    }
    if (Array.isArray(d) && d[0] && typeof d[0].msg === "string") {
      return d[0].msg;
    }
    return "";
  }

  function humanPhase(phase) {
    const m = {
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
    const panel = panelHost.querySelector(".terra-sdwan-sync-inline-panel");
    if (!panel) {
      return null;
    }
    const fill = panel.querySelector(".terra-sdwan-sync-fill");
    const status = panel.querySelector(".terra-sdwan-sync-status");
    const sub = panel.querySelector(".terra-sdwan-sync-sub");
    const closeBtn = panel.querySelector(".terra-sdwan-sync-close");
    const cancelBtn = panel.querySelector(".terra-sdwan-sync-cancel");
    const nameEl = panel.querySelector(".terra-sdwan-sync-inline-for");
    return { panelHost, panel, fill, status, sub, closeBtn, cancelBtn, nameEl };
  }

  function applyJobToInlineUi(ui, job) {
    if (!ui || !job) {
      return;
    }
    const pct = typeof job.percent === "number" ? job.percent : parseInt(String(job.percent || 0), 10) || 0;
    if (ui.fill) {
      ui.fill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
    }
    if (ui.status) {
      ui.status.textContent = `${humanPhase(job.phase)} — ${job.message || ""}`;
    }
    if (ui.sub) {
      let t = `Progress: ${pct}%`;
      if (job.status === "done" && job.rows_touched != null) {
        t += ` · Rows updated: ${job.rows_touched}`;
      }
      if (job.errors && job.error_detail) {
        t += ` · ${job.error_detail}`;
      }
      ui.sub.textContent = t;
    }
    const st = String(job.status || "");
    const terminal = st === "done" || st === "failed" || st === "cancelled";
    if (ui.closeBtn) {
      ui.closeBtn.disabled = !terminal;
    }
    if (ui.cancelBtn) {
      ui.cancelBtn.disabled = terminal || st === "";
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    refreshAll();
    setInterval(refreshAll, 30000);

    document.querySelectorAll(".terra-sdwan-sync-one").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const id = btn.getAttribute("data-instance-id");
        if (!id) {
          return;
        }
        const displayName = (btn.getAttribute("data-instance-name") || "").trim();
        const row = btn.closest("tr");
        const inlineRow = document.querySelector('[data-terra-sync-row-for="' + id + '"]');
        if (!inlineRow) {
          window.alert("Sync panel not found for this row.");
          return;
        }
        const ui = bindInlineSyncUi(inlineRow);
        if (!ui) {
          return;
        }
        if (ui.nameEl) {
          ui.nameEl.textContent = displayName ? `(${displayName})` : "";
        }

        btn.disabled = true;
        const orig = btn.textContent;
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

        let poll = null;
        let jobId = "";
        let finished = false;

        const stopPoll = function () {
          if (poll) {
            window.clearInterval(poll);
          }
          poll = null;
        };

        const cleanupUi = function () {
          stopPoll();
          if (row) {
            row.classList.remove("terra-sdwan-row--syncing");
          }
          btn.disabled = false;
          btn.textContent = orig;
        };

        const hideInline = function () {
          inlineRow.setAttribute("hidden", "hidden");
        };

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
              const cr = await fetch(`/api/v1/me/sync-sdwan-jobs/${encodeURIComponent(jobId)}/cancel`, {
                method: "POST",
                credentials: "same-origin",
              });
              if (!cr.ok) {
                let msg = "";
                try {
                  const b = await cr.json();
                  msg = detailFromBody(b) || "";
                } catch (_e) {
                  msg = "";
                }
                window.alert(msg || `Cancel request failed (${cr.status})`);
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

        try {
          const start = await fetch(`/api/v1/me/sync-sdwan-devices/${encodeURIComponent(id)}/async`, {
            method: "POST",
            credentials: "same-origin",
          });
          let body = {};
          try {
            body = await start.json();
          } catch (_e) {
            body = {};
          }
          if (!start.ok) {
            window.alert(detailFromBody(body) || `Could not start sync (${start.status})`);
            hideInline();
            cleanupUi();
            return;
          }
          jobId = body.job_id;
          if (!jobId) {
            window.alert("Server did not return a job id.");
            hideInline();
            cleanupUi();
            return;
          }

          if (ui.cancelBtn) {
            ui.cancelBtn.disabled = false;
          }

          const runPoll = async function () {
            if (finished) {
              return;
            }
            const r = await fetch(`/api/v1/me/sync-sdwan-jobs/${encodeURIComponent(jobId)}`, {
              credentials: "same-origin",
            });
            if (!r.ok) {
              return;
            }
            const j = await r.json();
            applyJobToInlineUi(ui, j);
            if (j.status === "done" || j.status === "failed" || j.status === "cancelled") {
              finished = true;
              stopPoll();
              if (ui.closeBtn) {
                ui.closeBtn.disabled = false;
                ui.closeBtn.focus();
              }
              if (j.status === "done" && j.errors && j.errors > 0) {
                const reason =
                  typeof j.error_detail === "string" && j.error_detail.trim() ? j.error_detail.trim() : "";
                window.alert(
                  reason
                    ? `Sync finished with errors.\n\n${reason}`
                    : "Sync finished with errors (see Details column after Close).",
                );
              }
            }
          };

          await runPoll();
          if (!finished) {
            poll = window.setInterval(runPoll, 500);
          }
        } catch (_e) {
          window.alert("Network error during sync.");
          hideInline();
          cleanupUi();
        }
      });
    });
  });
})();
