// Financial Sentiment Dashboard - frontend
//
// Talks to the Flask API in webapp/server.py (which is just a thin wrapper
// over storage/queries.py - all the real logic lives there). Polls every
// 60s to match the old Streamlit dashboard's auto-refresh cadence, but
// updates in place via fetch() instead of a full page rerun.

const state = {
  hours: 24,
  selectedTicker: null,
  overview: [],
  mainChart: null,
  sparklineCharts: {},
};

const REFRESH_MS = 60_000;

const SIGNAL_CLASS = { BUY: "buy", SELL: "sell", HOLD: "hold" };
const VERDICT_CLASS = {
  BULLISH: "bullish",
  BEARISH: "bearish",
  "MIXED/NEUTRAL": "mixed",
  "NO DATA": "nodata",
};

function fmtMoney(v) {
  return v === null || v === undefined ? "—" : `$${Number(v).toFixed(2)}`;
}
function fmtPct(v) {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${Number(v).toFixed(2)}%`;
}
function changeClass(v) {
  if (v === null || v === undefined) return "";
  return v >= 0 ? "up" : "down";
}

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> HTTP ${resp.status}`);
  return resp.json();
}

// --- KPI strip --------------------------------------------------------

function renderKpiStrip(rows) {
  const strip = document.getElementById("kpi-strip");
  strip.innerHTML = "";
  rows.forEach((row) => {
    const card = document.createElement("div");
    card.className = "kpi-card" + (row.ticker === state.selectedTicker ? " selected" : "");
    card.dataset.ticker = row.ticker;
    const chgClass = changeClass(row.day_change_pct);
    const signalClass = SIGNAL_CLASS[row.signal] || "hold";
    card.innerHTML = `
      <div class="kpi-ticker">${row.ticker}</div>
      <div class="kpi-price">${fmtMoney(row.price)}</div>
      <div class="kpi-change ${chgClass}">${chgClass === "up" ? "▲" : chgClass === "down" ? "▼" : ""} ${fmtPct(row.day_change_pct)}</div>
      <span class="kpi-signal ${signalClass}">${row.signal}</span>
    `;
    card.addEventListener("click", () => selectTicker(row.ticker));
    strip.appendChild(card);
  });
}

// --- Watchlist table ----------------------------------------------------

function renderTable(rows) {
  const body = document.getElementById("watchlist-body");
  body.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.className = row.ticker === state.selectedTicker ? "selected" : "";
    tr.dataset.ticker = row.ticker;
    const verdictClass = VERDICT_CLASS[row.verdict] || "nodata";
    const signalClass = SIGNAL_CLASS[row.signal] || "hold";
    tr.innerHTML = `
      <td><strong>${row.ticker}</strong></td>
      <td class="num">${fmtMoney(row.price)}</td>
      <td class="num ${changeClass(row.day_change_pct) === "up" ? "change-up" : "change-down"}">${fmtPct(row.day_change_pct)}</td>
      <td class="num">${row.bullish}</td>
      <td class="num">${row.bearish}</td>
      <td class="num">${row.neutral}</td>
      <td><span class="badge ${verdictClass}">${row.verdict}</span></td>
      <td><span class="badge ${signalClass}">${row.signal}</span></td>
      <td class="sparkline-cell"><canvas id="spark-${row.ticker}"></canvas></td>
    `;
    tr.addEventListener("click", () => selectTicker(row.ticker));
    body.appendChild(tr);
  });
}

async function renderSparklines(rows) {
  // Destroy old sparkline chart instances before re-creating (avoids
  // Chart.js "canvas already in use" errors on refresh).
  Object.values(state.sparklineCharts).forEach((c) => c.destroy());
  state.sparklineCharts = {};

  for (const row of rows) {
    const canvas = document.getElementById(`spark-${row.ticker}`);
    if (!canvas) continue;
    let history;
    try {
      const detail = await fetchJSON(`/api/ticker/${row.ticker}?hours=${state.hours}`);
      history = detail.price_history;
    } catch (e) {
      continue;
    }
    if (!history || history.length < 2) continue;
    const lineColor = changeClass(row.day_change_pct) === "down" ? "#ef4444" : "#22c55e";
    state.sparklineCharts[row.ticker] = new Chart(canvas, {
      type: "line",
      data: {
        labels: history.map((h) => h.fetched_at),
        datasets: [{ data: history.map((h) => h.price), borderColor: lineColor, borderWidth: 1.5, pointRadius: 0, tension: 0.3 }],
      },
      options: {
        responsive: false,
        animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false } },
      },
    });
  }
}

// --- Detail panel (chart + stats + posts) --------------------------------

function renderStats(detail) {
  document.getElementById("chart-ticker-title").textContent = detail.ticker;
  document.getElementById("chart-subtitle").textContent = `last ${state.hours}h`;

  const signalEl = document.getElementById("stat-signal");
  signalEl.textContent = detail.signal.signal;
  signalEl.className = "stat-badge " + (SIGNAL_CLASS[detail.signal.signal] || "hold");
  document.getElementById("stat-reasoning").textContent = detail.signal.reasoning;

  document.getElementById("stat-verdict").textContent = detail.verdict;
  document.getElementById("stat-price").textContent =
    detail.price_info && detail.price_info.price != null
      ? `${fmtMoney(detail.price_info.price)} (${fmtPct(detail.price_info.day_change_pct)})`
      : "—";
  const totalPosts = detail.counts.bullish + detail.counts.bearish + detail.counts.neutral;
  document.getElementById("stat-posts").textContent = totalPosts;

  const socialEl = document.getElementById("stat-social");
  socialEl.innerHTML = "";
  const lines = [];
  for (const [platform, label] of [["reddit", "Reddit"], ["twitter", "Twitter/X"]]) {
    const info = detail.social_agg && detail.social_agg[platform];
    if (info && info.mention != null) {
      lines.push(
        `<div class="social-line"><strong>${label}</strong> (Finnhub): ${info.mention} mentions, ` +
          `+${info.positive_score.toFixed(2)} / -${info.negative_score.toFixed(2)}</div>`
      );
    }
  }
  if (lines.length) {
    socialEl.innerHTML =
      `<div class="stat-label" style="margin-bottom:6px;">Supplementary (not in counts above)</div>` + lines.join("");
  }
}

// Price history is recorded roughly every ingestion cycle (~15 min) with
// full timestamps; sentiment_timeseries is already bucketed hourly by the
// backend (substr(scored_at, 1, 13)). Plotting both as separate {x, y}
// object-points on a shared *category* axis doesn't work reliably - a
// category scale positions points by matching against a single shared
// `labels` array, not by parsing arbitrary x values - so the two series
// need to be aligned onto ONE shared array of hour buckets first, with
// gaps left as null (and spanGaps used so a thin data window still draws
// a connected line instead of nothing).
function alignToHourlyBuckets(priceHistory, sentimentSeries) {
  const priceByHour = new Map();
  for (const p of priceHistory) {
    if (typeof p.fetched_at === "string" && p.fetched_at.length >= 13) {
      priceByHour.set(p.fetched_at.slice(0, 13), p.price); // last-wins, history is ASC
    }
  }
  const sentimentByHour = new Map();
  for (const s of sentimentSeries) {
    sentimentByHour.set(s.bucket, s.avg_compound);
  }

  const hours = Array.from(new Set([...priceByHour.keys(), ...sentimentByHour.keys()])).sort();
  return {
    labels: hours,
    price: hours.map((h) => (priceByHour.has(h) ? priceByHour.get(h) : null)),
    sentiment: hours.map((h) => (sentimentByHour.has(h) ? sentimentByHour.get(h) : null)),
  };
}

function renderMainChart(detail) {
  const ctx = document.getElementById("main-chart");
  const emptyState = document.getElementById("chart-empty-state");
  if (state.mainChart) {
    state.mainChart.destroy();
    state.mainChart = null;
  }

  const priceHistory = detail.price_history || [];
  const sentimentSeries = detail.sentiment_timeseries || [];
  const { labels, price, sentiment } = alignToHourlyBuckets(priceHistory, sentimentSeries);

  const pointCount = labels.length;
  if (pointCount === 0) {
    ctx.style.display = "none";
    emptyState.style.display = "block";
    emptyState.textContent = `No price or sentiment data yet for ${detail.ticker} in this window - run main.py a few more times (on its 15-min schedule) to build up history.`;
    return;
  }
  ctx.style.display = "";
  emptyState.style.display = "none";

  if (typeof Chart === "undefined") {
    emptyState.style.display = "block";
    emptyState.textContent = "Chart.js failed to load (check your internet connection / browser console) - the rest of the dashboard still works.";
    return;
  }

  // With very little history so far (a run or two), a hairline-only line
  // (pointRadius 0) can look completely blank - a visible dot at each
  // point ensures sparse data is still seen, not just a smooth line once
  // there are many points.
  const pointRadius = pointCount <= 3 ? 3 : 0;

  state.mainChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Price ($)",
          data: price,
          borderColor: "#3b82f6",
          backgroundColor: "rgba(59,130,246,0.12)",
          fill: true,
          tension: 0.3,
          pointRadius,
          spanGaps: true,
          yAxisID: "y",
        },
        {
          label: "Avg sentiment (VADER compound)",
          data: sentiment,
          borderColor: "#f59e0b",
          borderDash: [4, 4],
          fill: false,
          tension: 0.3,
          pointRadius,
          spanGaps: true,
          yAxisID: "y1",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#8a92a6", boxWidth: 12, font: { size: 11 } } },
      },
      scales: {
        x: { ticks: { color: "#8a92a6", maxTicksLimit: 8 }, grid: { color: "#232938" } },
        y: { position: "left", ticks: { color: "#8a92a6" }, grid: { color: "#232938" }, title: { display: true, text: "Price ($)", color: "#8a92a6" } },
        y1: { position: "right", min: -1, max: 1, ticks: { color: "#8a92a6" }, grid: { display: false }, title: { display: true, text: "Sentiment", color: "#8a92a6" } },
      },
    },
  });
}

function renderPosts(detail) {
  document.getElementById("posts-title").textContent = `Recent chatter — ${detail.ticker}`;
  const list = document.getElementById("posts-list");
  list.innerHTML = "";
  if (!detail.recent_posts || detail.recent_posts.length === 0) {
    list.innerHTML = `<li class="muted">No posts scored yet for ${detail.ticker} in this window.</li>`;
    return;
  }
  detail.recent_posts.forEach((post) => {
    const li = document.createElement("li");
    const badgeClass = VERDICT_CLASS[post.label ? post.label.toUpperCase() : ""] ||
      (post.label === "bullish" ? "bullish" : post.label === "bearish" ? "bearish" : "mixed");
    li.innerHTML = `
      <div class="post-meta">
        <span class="post-source">${post.source}</span>
        <span class="badge ${badgeClass}">${post.label}</span>
        <span>${new Date(post.scored_at).toLocaleString()}</span>
      </div>
      <div class="post-text">${escapeHtml(post.text || "")}</div>
    `;
    list.appendChild(li);
  });
}

async function loadEvents() {
  const list = document.getElementById("events-list");
  if (!list) return;
  try {
    const suffix = state.selectedTicker ? `?ticker=${state.selectedTicker}` : "";
    const events = await fetchJSON(`/api/events${suffix}`);
    list.innerHTML = events.length ? "" : '<li class="muted">No official events ingested yet.</li>';
    events.forEach((event) => {
      const li = document.createElement("li");
      const label = event.ticker ? `${event.ticker} · ${event.category}` : event.category;
      li.innerHTML = `<div class="post-meta"><span class="post-source">${escapeHtml(event.source)}</span><span>${escapeHtml(label)}</span><span>${event.published_at ? new Date(event.published_at).toLocaleString() : ""}</span></div><div class="post-text"><a href="${encodeURI(event.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(event.title)}</a></div>`;
      list.appendChild(li);
    });
  } catch (e) {
    console.error("Failed to load official events:", e);
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// --- Orchestration -------------------------------------------------------

async function selectTicker(ticker) {
  state.selectedTicker = ticker;
  document.querySelectorAll(".kpi-card").forEach((c) => c.classList.toggle("selected", c.dataset.ticker === ticker));
  document.querySelectorAll("#watchlist-body tr").forEach((r) => r.classList.toggle("selected", r.dataset.ticker === ticker));
  await loadDetail();
  await loadEvents();
}

async function loadDetail() {
  if (!state.selectedTicker) return;

  let detail;
  try {
    detail = await fetchJSON(`/api/ticker/${state.selectedTicker}?hours=${state.hours}`);
  } catch (e) {
    console.error("Failed to load ticker detail:", e);
    return;
  }

  // Each panel is rendered independently - a bug or exception in one
  // (e.g. the chart) must never prevent the others (e.g. the posts feed)
  // from rendering. This is exactly the failure mode that made the
  // "Recent chatter" panel appear blank even though the API had data.
  try {
    renderStats(detail);
  } catch (e) {
    console.error("Failed to render stats:", e);
  }
  try {
    renderMainChart(detail);
  } catch (e) {
    console.error("Failed to render main chart:", e);
    const emptyState = document.getElementById("chart-empty-state");
    document.getElementById("main-chart").style.display = "none";
    emptyState.style.display = "block";
    emptyState.textContent = "Something went wrong rendering the chart - check the browser console for details.";
  }
  try {
    renderPosts(detail);
  } catch (e) {
    console.error("Failed to render posts:", e);
  }
}

async function loadOverview() {
  try {
    const data = await fetchJSON(`/api/overview?hours=${state.hours}`);
    state.overview = data.tickers;
    if (!state.overview.length) {
      document.getElementById("kpi-strip").innerHTML =
        '<div class="muted">No data yet — run <code>python main.py</code> at least once, then reload this page.</div>';
      return;
    }
    if (!state.selectedTicker) {
      state.selectedTicker = state.overview[0].ticker;
    }
    renderKpiStrip(state.overview);
    renderTable(state.overview);
    renderSparklines(state.overview);
    document.getElementById("last-updated").textContent = `Last checked: ${new Date().toLocaleTimeString()}`;
    await loadDetail();
  } catch (e) {
    console.error("Failed to load overview:", e);
    document.getElementById("last-updated").textContent = "Failed to reach the dashboard server — is main.py's database present?";
  }
}

// --- Prediction accuracy log ----------------------------------------------

// Renders one BUY-or-SELL sub-row inside an accuracy card - added
// 2026-07-12 so a strong-on-BUYs/weak-on-SELLs rule (or vice versa) is
// visible instead of hidden inside one pooled percentage.
function bySignalRow(label, s) {
  if (!s || s.graded === 0) return `<div class="accuracy-subrow muted">${label}: no graded calls yet</div>`;
  return `<div class="accuracy-subrow">${label}: <strong>${s.accuracy_pct}%</strong> (${s.correct}/${s.graded})</div>`;
}

function renderAccuracySummary(accuracy) {
  const container = document.getElementById("accuracy-summary");
  container.innerHTML = "";
  for (const key of ["horizon_4h", "horizon_24h"]) {
    const stats = accuracy[key];
    const label = key === "horizon_4h" ? "4-hour accuracy" : "24-hour accuracy";
    const graded = stats.correct + stats.incorrect;
    let pctClass = "none";
    let pctText = "—";
    if (graded > 0) {
      pctText = `${stats.accuracy_pct}%`;
      pctClass = stats.accuracy_pct >= 50 ? "good" : "bad";
    }
    // Baseline comparison, added 2026-07-12: markets drift upward over
    // time, so a BUY-heavy rule can look "accurate" purely by riding that
    // drift. Showing "price simply rose X% of the time anyway" next to the
    // rule's own accuracy lets you tell skill from drift at a glance.
    const baselineText = stats.baseline_n > 0
      ? `Baseline: price rose in ${stats.baseline_up_pct}% of all ${stats.baseline_n} graded windows anyway`
      : "Baseline: not enough graded windows yet";
    const ciText = graded > 0
      ? `95% confidence range: ${stats.accuracy_ci_low}%–${stats.accuracy_ci_high}%`
      : "";
    const lowSampleWarning = stats.low_sample && graded > 0
      ? `<div class="accuracy-warning">Only ${graded} graded call(s) so far - too few to trust this percentage yet.</div>`
      : "";

    const card = document.createElement("div");
    card.className = "accuracy-card";
    card.innerHTML = `
      <div class="accuracy-horizon">${label}</div>
      <div class="accuracy-pct ${pctClass}">${pctText}</div>
      <div class="accuracy-detail">${stats.correct} correct / ${stats.incorrect} incorrect (${graded} graded)</div>
      <div class="accuracy-detail">${stats.hold} HOLD (no call) · ${stats.pending} pending</div>
      <div class="accuracy-detail muted">${ciText}</div>
      <div class="accuracy-detail muted">${baselineText}</div>
      ${lowSampleWarning}
      <div class="accuracy-by-signal">
        ${bySignalRow("BUY", stats.by_signal && stats.by_signal.BUY)}
        ${bySignalRow("SELL", stats.by_signal && stats.by_signal.SELL)}
      </div>
    `;
    container.appendChild(card);
  }
}

function resultPill(evalResult) {
  if (!evalResult) return '<span class="result-pill pending">pending</span>';
  if (evalResult.correct === null || evalResult.correct === undefined) {
    return '<span class="result-pill hold">n/a</span>';
  }
  const pctText = evalResult.price_change_pct != null ? ` (${evalResult.price_change_pct >= 0 ? "+" : ""}${evalResult.price_change_pct.toFixed(1)}%)` : "";
  return evalResult.correct
    ? `<span class="result-pill correct">correct${pctText}</span>`
    : `<span class="result-pill incorrect">incorrect${pctText}</span>`;
}

// Source mix for one logged signal, e.g. "STOCKTWITS 12 · FINNHUB 4" - added
// 2026-07-12 so it's possible to eyeball which source(s) actually drove a
// given call, ahead of properly slicing accuracy by source once there's
// enough history.
function sourceBadges(sourceBreakdown) {
  if (!sourceBreakdown || Object.keys(sourceBreakdown).length === 0) {
    return '<span class="muted">—</span>';
  }
  return Object.entries(sourceBreakdown)
    .map(([source, counts]) => {
      const total = (counts.bullish || 0) + (counts.bearish || 0) + (counts.neutral || 0);
      return `<span class="source-tag">${source} ${total}</span>`;
    })
    .join(" ");
}

function renderSignalLog(rows) {
  const body = document.getElementById("signal-log-body");
  body.innerHTML = "";
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="muted">No signal changes logged yet - this fills in as BUY/SELL/HOLD calls change over time.</td></tr>';
    return;
  }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const signalClass = SIGNAL_CLASS[row.signal] || "hold";
    tr.innerHTML = `
      <td><strong>${row.ticker}</strong></td>
      <td><span class="badge ${signalClass}">${row.signal}</span></td>
      <td>${new Date(row.logged_at).toLocaleString()}</td>
      <td class="num">${fmtMoney(row.price_at_signal)}</td>
      <td>${sourceBadges(row.source_breakdown)}</td>
      <td>${resultPill(row.eval_4h)}</td>
      <td>${resultPill(row.eval_24h)}</td>
    `;
    body.appendChild(tr);
  });
}

async function loadAccuracyLog() {
  try {
    const [accuracy, log] = await Promise.all([
      fetchJSON("/api/accuracy"),
      fetchJSON("/api/signal-log?limit=50"),
    ]);
    renderAccuracySummary(accuracy);
    renderSignalLog(log);
  } catch (e) {
    console.error("Failed to load accuracy log:", e);
  }
}

function setupTabs() {
  document.getElementById("lookback-tabs").addEventListener("click", (e) => {
    if (e.target.tagName !== "BUTTON") return;
    document.querySelectorAll("#lookback-tabs button").forEach((b) => b.classList.remove("active"));
    e.target.classList.add("active");
    state.hours = parseInt(e.target.dataset.hours, 10);
    loadOverview();
  });
}

function refreshAll() {
  loadOverview();
  loadAccuracyLog();
  loadEvents();
}

setupTabs();
refreshAll();
setInterval(refreshAll, REFRESH_MS);
