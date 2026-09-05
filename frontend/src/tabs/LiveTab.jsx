import { useEffect, useState } from "react";
import { api } from "../api";
import { ACTION_LABEL, humanize, formatMoney, displayReasoning, shortReason, actionColor } from "../labels";

const AUTO_REFRESH_MS = 4000;
const RECOVERY_CHECK_MS = 8000;

export default function LiveTab({ apiBase }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [recovered, setRecovered] = useState({}); // transaction_id -> amount

  // Silent: updates the list in place, no "Loading…" flash and no reset of
  // per-transaction recovery status already known -- meant to run every
  // few seconds in the background without disrupting whatever the user is
  // looking at (e.g. mid-payment in the embedded checkout below).
  function silentRefresh() {
    api.liveTransactions().then((d) => setRows(d.transactions)).catch((e) => setError(e.message));
  }

  // Hard: the manual "Refresh" button and the initial load -- also clears
  // any stale recovered-amount tracking so it recomputes from scratch.
  function refresh() {
    setRows(null);
    setRecovered({});
    silentRefresh();
  }

  useEffect(() => {
    refresh();
    const id = setInterval(silentRefresh, AUTO_REFRESH_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  function handleRecovered(transactionId, amount) {
    setRecovered((prev) => (prev[transactionId] != null ? prev : { ...prev, [transactionId]: amount }));
  }

  const totalRecovered = Object.values(recovered).reduce((sum, a) => sum + (a || 0), 0);
  const totalSpent = (rows || []).reduce((sum, r) => sum + (r.intervention_cost || 0), 0);

  return (
    <div>
      <h2>Real payments, real time</h2>
      <p style={{ color: "var(--ink-secondary)" }}>
        Everything else runs on a simulated batch. This tab shows actual payment failures from a connected
        Razorpay account, scored and decided by the same engine, with no human involved in between.
      </p>

      <details open style={{ marginBottom: 20 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: "0.95rem" }}>
          {"💳"} Make a real transaction
        </summary>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.85rem", marginTop: 8 }}>
          A real Razorpay Test Mode checkout, embedded directly — no real money moves. Pick a customer
          type, pay with any card, or use a{" "}
          <a href="https://razorpay.com/docs/payments/payments/test-card-details/" target="_blank" rel="noopener noreferrer">
            documented test failure card
          </a>{" "}
          to see a real failure flow through the agent below, live. You're stepping into that
          customer's shoes for this — once it fails, the box that appears (including its
          "Pay now" button) is written to them, not to you as the merchant; the same moment
          shows up on this dashboard's own Live entries below, in your voice, once it's done.
        </p>
        <iframe
          src={`${apiBase}/checkout`}
          title="Recovery Copilot checkout"
          style={{ width: "100%", height: 760, border: "1px solid var(--border)", borderRadius: 12, marginTop: 10 }}
        />
      </details>

      <button className="btn secondary" onClick={refresh} style={{ marginBottom: 16 }}>{"🔄"} Refresh</button>

      {error && <div className="empty-state">Couldn't load live transactions: {error}</div>}
      {!error && !rows && <div className="loading-state">Loading…</div>}
      {!error && rows && rows.length === 0 && (
        <div className="empty-state">
          No real transactions yet — pay (and fail) one above, then hit Refresh.
          See <code>pitch/razorpay_live_setup.md</code> for the full setup.
        </div>
      )}
      {!error && rows && rows.length > 0 && (
        <>
          <div className="kpi-row" style={{ marginBottom: 16 }}>
            <div className="kpi">
              <div className="label">Real transactions handled</div>
              <div className="value">{rows.length}</div>
            </div>
            <div className="kpi">
              <div className="label">Total amount involved</div>
              <div className="value">{formatMoney(rows.reduce((sum, r) => sum + (r.amount || 0), 0))}</div>
            </div>
            <div className="kpi">
              <div className="label">Most common response</div>
              <div className="value" style={{ fontSize: "1.1rem" }}>
                {ACTION_LABEL[mostCommon(rows.map((r) => r.action))] || "—"}
              </div>
            </div>
            <div className="kpi">
              <div className="label">Recovered so far</div>
              <div className="value" style={{ color: "var(--status-good)" }}>{formatMoney(totalRecovered)}</div>
            </div>
            <div className="kpi">
              <div className="label">Spent recovering it</div>
              <div className="value">{formatMoney(totalSpent)}</div>
              {totalRecovered > 0 && (
                <div className="delta" style={{ color: "var(--ink-muted)" }}>
                  {((totalSpent / totalRecovered) * 100).toFixed(1)}% of what came back
                </div>
              )}
            </div>
          </div>

          {rows.map((r) => (
            <LiveEntry key={r.transaction_id} entry={r} onRecovered={handleRecovered} />
          ))}
        </>
      )}
    </div>
  );
}

function ExecutionStatus({ executed, detail }) {
  if (!detail) return null;

  // The instant "Pay now" action -- shown whenever a real link exists,
  // regardless of whether an email also went out. This is the customer's
  // own in-session action (they were just on the checkout page), not
  // proactive outreach, so it's never gated by quiet hours.
  const payNow = detail.short_url && (
    <a
      href={detail.short_url} target="_blank" rel="noopener noreferrer"
      className="btn" style={{ display: "block", textAlign: "center", textDecoration: "none", marginTop: 8 }}
    >
      Pay now
    </a>
  );

  if (detail.deferred_quiet_hours) {
    return (
      <div className="status-box thinking" style={{ marginTop: 10 }}>
        {"😴"} It's quiet hours (10pm–8am) for this customer, so the proactive email was held back — but
        the link above (if present) works immediately since they were already on the checkout page.
        {payNow}
      </div>
    );
  }
  if (executed && detail.type === "payment_link") {
    return (
      <div className="status-box ready" style={{ marginTop: 10 }}>
        {"✅"} A real Razorpay Payment Link was created.
        {payNow}
        <div style={{ marginTop: 6, fontSize: "0.82rem" }}>
          {detail.emailed ? `✅ Also emailed to ${detail.sent_to}`
            : `⚠️ Not emailed${detail.email_error ? `: ${detail.email_error}` : " -- no email delivery configured."}`}
        </div>
      </div>
    );
  }
  if (executed && detail.type === "email") {
    return (
      <div className="status-box ready" style={{ marginTop: 10 }}>
        {"✅"} A real email was sent to <strong>{detail.sent_to}</strong>
        {payNow}
      </div>
    );
  }
  return (
    <div className="status-box error" style={{ marginTop: 10 }}>
      {"⚠️"} Decision made, but execution failed: {detail.error || "unknown error"}
    </div>
  );
}

function mostCommon(arr) {
  const counts = {};
  let best = null, bestCount = 0;
  for (const v of arr) {
    counts[v] = (counts[v] || 0) + 1;
    if (counts[v] > bestCount) { best = v; bestCount = counts[v]; }
  }
  return best;
}

function LiveEntry({ entry, onRecovered }) {
  const [showTechnical, setShowTechnical] = useState(false);
  const [showFullReasoning, setShowFullReasoning] = useState(false);
  const [recovery, setRecovery] = useState(null);
  const ts = entry.timestamp ? new Date(entry.timestamp).toUTCString().replace("GMT", "UTC") : "";
  const hasLink = entry.execution_detail && entry.execution_detail.link_id;

  useEffect(() => {
    if (!hasLink) return;
    let cancelled = false;
    function check() {
      api.recoveryStatus(entry.transaction_id).then((d) => {
        if (cancelled) return;
        setRecovery(d);
        if (d.recovered) {
          onRecovered(entry.transaction_id, d.recovered_amount);
          clearInterval(id); // it's paid -- stop spending API calls checking further
        }
      }).catch(() => {});
    }
    check();
    // Keeps checking -- a link created now might get paid minutes later,
    // and this is what makes "recovered" genuinely live rather than a
    // one-time snapshot at the moment the entry first appeared.
    const id = setInterval(check, RECOVERY_CHECK_MS);
    return () => { cancelled = true; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.transaction_id]);

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <strong>{formatMoney(entry.amount)}</strong> · {humanize(entry.failure_reason)} · {humanize(entry.customer_segment || "unknown")} customer
          {" "}→ <span style={{ color: actionColor(entry.action), fontWeight: 700 }}>{ACTION_LABEL[entry.action] || entry.action}</span>
          {(entry.recoverability_score != null || entry.intervention_cost != null) && (
            <div style={{ color: "var(--ink-muted)", fontSize: "0.82rem" }}>
              {entry.recoverability_score != null && <>Confidence: {Math.round(entry.recoverability_score * 100)}%</>}
              {entry.recoverability_score != null && entry.intervention_cost != null && " · "}
              {entry.intervention_cost != null && <>Cost to recover: {formatMoney(entry.intervention_cost)}</>}
            </div>
          )}
          {recovery && recovery.recovered && (
            <div style={{ color: "var(--status-good)", fontWeight: 700, fontSize: "0.85rem", marginTop: 4 }}>
              {"✅"} Recovered: {formatMoney(recovery.recovered_amount)}
            </div>
          )}
          {recovery && hasLink && !recovery.recovered && (
            <div style={{ color: "var(--ink-muted)", fontSize: "0.78rem", marginTop: 4 }}>
              Not paid yet ({recovery.status || "pending"})
            </div>
          )}
        </div>
        <div style={{ textAlign: "right", fontSize: "0.78rem", color: "var(--ink-muted)" }}>
          <div>{ts}</div>
          <code>{entry.transaction_id}</code>
        </div>
      </div>

      {Array.isArray(entry.reasoning) && entry.reasoning.length > 0 && (
        <div style={{ marginTop: 10, fontSize: "0.9rem", color: "var(--ink-secondary)" }}>
          <strong>Why: </strong>
          {showFullReasoning ? (
            <ul className="reasoning-list" style={{ marginTop: 6 }}>
              {entry.reasoning.map((r, i) => <li key={i}>{displayReasoning(r)}</li>)}
            </ul>
          ) : (
            <span>{shortReason(entry.reasoning)}</span>
          )}
          {" "}
          <button
            onClick={() => setShowFullReasoning(!showFullReasoning)}
            style={{ background: "none", border: "none", color: "var(--blue)", cursor: "pointer", fontSize: "0.85em", padding: 0 }}
          >
            {showFullReasoning ? "Show less" : "Show more"}
          </button>
        </div>
      )}

      <ExecutionStatus executed={entry.executed} detail={entry.execution_detail} />

      <button className="btn secondary" style={{ marginTop: 10 }} onClick={() => setShowTechnical(!showTechnical)}>
        {"🔧"} {showTechnical ? "Hide" : "Show"} technical details
      </button>
      {showTechnical && (
        <div style={{ marginTop: 10, fontSize: "0.85rem" }}>
          {Array.isArray(entry.reasoning) && entry.reasoning.length > 0 && (
            <p><strong>Raw reasoning string(s):</strong> {entry.reasoning.map((r) => `"${r}"`).join("; ")}</p>
          )}
          <p><strong>Event:</strong> <code>{entry.event}</code> from Razorpay's webhook</p>
          <p>
            <strong>Raw Razorpay error:</strong> <code>{entry.raw_error_reason || "—"}</code> /{" "}
            <code>{entry.raw_error_code || "—"}</code> — {entry.raw_error_description || "—"}
          </p>
        </div>
      )}
    </div>
  );
}
