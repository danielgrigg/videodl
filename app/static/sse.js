// Tiny SSE client: subscribe to /events and re-render the job rows live.
// When a job finishes, reload so the new video tile appears in the grid.

(function () {
  const jobsEl = document.getElementById("jobs");
  if (!jobsEl) return;

  let sawActive = false;

  const source = new EventSource("/events");

  source.addEventListener("jobs", (event) => {
    const jobs = JSON.parse(event.data);

    const active = jobs.some(
      (j) => j.state === "queued" || j.state === "downloading" || j.state === "processing"
    );

    // A job that was in flight has now settled: refresh to pick up the new tile.
    if (sawActive && !active) {
      window.location.reload();
      return;
    }
    sawActive = active;

    jobsEl.replaceChildren(...jobs.map(renderJob));
  });

  function renderJob(j) {
    const row = document.createElement("div");
    row.className = `job state-${j.state}`;
    row.dataset.id = j.id;
    row.appendChild(span("job-url", j.url, j.url));
    row.appendChild(span("job-state", j.state));
    row.appendChild(span("job-pct", j.pct || ""));
    row.appendChild(span("job-speed", j.speed || ""));
    if (j.error) row.appendChild(span("job-error", j.error, j.error));
    return row;
  }

  function span(cls, text, title) {
    const el = document.createElement("span");
    el.className = cls;
    el.textContent = text;
    if (title) el.title = title;
    return el;
  }
})();
