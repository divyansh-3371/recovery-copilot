import { useEffect, useState } from "react";
import { api } from "../api";
import {
  ACTION_LABEL, RISK_TYPE_LABEL, humanize, formatMoney, displayReasoning, shortReason,
  friendlyFeature, strength, actionColor,
} from "../labels";

export default function TransactionsTab({ seed }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ risk_type: "", agent_action: "", customer_segment: "" });
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showTechnical, setShowTechnical] = useState(false);
  const [showFullReasoning, setShowFullReasoning] = useState(false);

  useEffect(() => {
    setRows(null);
    setSelectedId(null);
    setDetail(null);
    const params = {};
    if (filters.risk_type) params.risk_type = filters.risk_type;
    if (filters.agent_action) params.action = filters.agent_action;
    if (filters.customer_segment) params.customer_segment = filters.customer_segment;

    Promise.all([
      api.transactions(seed, params).then((d) => d.transactions),
      // Real transactions are always risk_type=payment_failure -- if a
      // filter picked something else, they'd never match anyway, so skip
      // fetching them at all rather than fetch-then-discard.
      (!filters.risk_type || filters.risk_type === "payment_failure")
        ? api.liveTransactions().then((d) => d.transactions.map(normalizeLiveRow))
        : Promise.resolve([]),
    ]).then(([synthetic, live]) => {
      const filteredLive = live.filter((r) =>
        (!filters.agent_action || r.agent_action === filters.agent_action) &&
        (!filters.customer_segment || r.customer_segment === filters.customer_segment)
      );
      // Real transactions first -- they're what a merchant would actually
      // want to see before a synthetic demo batch.
      setRows([...filteredLive, ...synthetic]);
    }).catch((e) => setError(e.message));
  }, [seed, filters]);

  useEffect(() => {
    if (!selectedId) return;
    setDetail(null);
    setShowFullReasoning(false);
    const row = (rows || []).find((r) => r.transaction_id === selectedId);
    if (row && row._source === "live") {
      setDetail({ _source: "live", ...row._liveEntry });
      return;
    }
    api.transactionDetail(selectedId, seed).then((d) => setDetail({ _source: "synthetic", ...d })).catch((e) => setError(e.message));
  }, [selectedId, seed, rows]);

  if (error) return <div className="empty-state">Couldn't load transactions: {error}</div>;

  const riskTypes = [...new Set((rows || []).map((r) => r.risk_type))];
  const actions = [...new Set((rows || []).map((r) => r.agent_action))];
  const segments = [...new Set((rows || []).map((r) => r.customer_segment))];

  return (
    <div>
      <h2>All transactions</h2>
      <p style={{ color: "var(--ink-secondary)" }}>Every payment issue Recovery Copilot has handled this period — real ones first, then the simulated batch.</p>

      <div className="grid-3" style={{ marginBottom: 16 }}>
        <div>
          <label className="field-label">Issue type</label>
          <select value={filters.risk_type} onChange={(e) => setFilters({ ...filters, risk_type: e.target.value })}>
            <option value="">All</option>
            {riskTypes.map((r) => <option key={r} value={r}>{RISK_TYPE_LABEL[r] || r}</option>)}
          </select>
        </div>
        <div>
          <label className="field-label">Status</label>
          <select value={filters.agent_action} onChange={(e) => setFilters({ ...filters, agent_action: e.target.value })}>
            <option value="">All</option>
            {actions.map((a) => <option key={a} value={a}>{ACTION_LABEL[a] || a}</option>)}
          </select>
        </div>
        <div>
          <label className="field-label">Customer type</label>
          <select value={filters.customer_segment} onChange={(e) => setFilters({ ...filters, customer_segment: e.target.value })}>
            <option value="">All</option>
            {segments.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
        </div>
      </div>

      {!rows ? (
        <div className="loading-state">Loading…</div>
      ) : (
        <div className="card" style={{ maxHeight: 340, overflowY: "auto", padding: 0 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Source</th><th>Transaction</th><th>Issue</th><th>Reason</th><th>Amount</th>
                <th>Customer</th><th>Confidence</th><th>Action</th><th>Cost to recover</th><th>Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.transaction_id} onClick={() => setSelectedId(r.transaction_id)}>
                  <td>
                    {r._source === "live"
                      ? <span className="badge critical" title="A real webhook-driven transaction">Live</span>
                      : <span className="badge" style={{ background: "#eef0f3", color: "var(--ink-muted)" }}>Demo</span>}
                  </td>
                  <td><code>{r.transaction_id}</code></td>
                  <td>{RISK_TYPE_LABEL[r.risk_type] || r.risk_type}</td>
                  <td>{humanize(r.failure_reason)}</td>
                  <td>{formatMoney(r.amount)}</td>
                  <td>{humanize(r.customer_segment)}</td>
                  <td>{r.recoverability_score != null ? `${Math.round(r.recoverability_score * 100)}%` : "—"}</td>
                  <td style={{ color: actionColor(r.agent_action), fontWeight: 600 }}>{ACTION_LABEL[r.agent_action] || r.agent_action}</td>
                  <td>{r.intervention_cost != null ? formatMoney(r.intervention_cost) : "—"}</td>
                  <td>{r.agent_resolved ? "✅ Recovered" : "In progress"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && detail && detail._source === "live" && (
        <div style={{ marginTop: 20 }}>
          <h3>Transaction detail <span className="badge critical" style={{ marginLeft: 6 }}>Live</span></h3>
          <div className="card">
            <p><strong>Amount:</strong> {formatMoney(detail.amount)} · <strong>Reason:</strong> {humanize(detail.failure_reason)} ·{" "}
              <strong>Customer:</strong> {humanize(detail.customer_segment || "unknown")}</p>
            <p><strong>What we did:</strong> <span style={{ color: actionColor(detail.action), fontWeight: 700 }}>{ACTION_LABEL[detail.action] || detail.action}</span></p>
            {detail.recoverability_score != null && <p><strong>Confidence:</strong> {Math.round(detail.recoverability_score * 100)}%</p>}
            {detail.intervention_cost != null && <p><strong>Cost to recover:</strong> {formatMoney(detail.intervention_cost)}</p>}
            {Array.isArray(detail.reasoning) && detail.reasoning.length > 0 && (
              <p>
                <strong>Why: </strong>
                {showFullReasoning ? (
                  <ul className="reasoning-list" style={{ marginTop: 6 }}>
                    {detail.reasoning.map((r, i) => <li key={i}>{displayReasoning(r)}</li>)}
                  </ul>
                ) : shortReason(detail.reasoning)}
                {" "}
                <button
                  onClick={() => setShowFullReasoning(!showFullReasoning)}
                  style={{ background: "none", border: "none", color: "var(--blue)", cursor: "pointer", fontSize: "0.85em", padding: 0 }}
                >
                  {showFullReasoning ? "Show less" : "Show more"}
                </button>
              </p>
            )}
            {detail.execution_detail && (
              <p style={{ fontSize: "0.9rem" }}>
                {detail.execution_detail.short_url && (
                  <>
                    <strong>Payment link:</strong>{" "}
                    <a href={detail.execution_detail.short_url} target="_blank" rel="noopener noreferrer">{detail.execution_detail.short_url}</a><br />
                  </>
                )}
                {detail.execution_detail.sent_to && <><strong>Emailed to:</strong> {detail.execution_detail.sent_to}<br /></>}
                {detail.execution_detail.error && <span style={{ color: "var(--status-critical)" }}>Execution failed: {detail.execution_detail.error}</span>}
              </p>
            )}
          </div>

          <div className="card" style={{ marginTop: 16 }}>
            <button className="btn secondary" onClick={() => setShowTechnical(!showTechnical)}>
              {"🔧"} {showTechnical ? "Hide" : "Show"} technical details
            </button>
            {showTechnical && (
              <div style={{ marginTop: 12, fontSize: "0.85rem" }}>
                <p><strong>Transaction ID:</strong> <code>{detail.transaction_id}</code></p>
                <p><strong>Event:</strong> <code>{detail.event}</code> from Razorpay's webhook</p>
                <p>
                  <strong>Raw Razorpay error:</strong> <code>{detail.raw_error_reason || "—"}</code> /{" "}
                  <code>{detail.raw_error_code || "—"}</code> — {detail.raw_error_description || "—"}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {selectedId && detail && detail._source === "synthetic" && (
        <div style={{ marginTop: 20 }}>
          <h3>Transaction detail</h3>
          <div className="grid-2">
              <div className="card">
                <p><strong>Customer:</strong> {detail.customer_name} ({humanize(detail.customer_segment)})</p>
                <p><strong>Amount:</strong> {formatMoney(detail.amount)} · <strong>Issue:</strong> {RISK_TYPE_LABEL[detail.risk_type] || detail.risk_type}</p>
                <p><strong>Reason:</strong> {humanize(detail.failure_reason)}</p>
                <p><strong>Confidence:</strong> {Math.round(detail.score * 100)}%</p>
                <strong>Why we think this:</strong>
                <ul className="reasoning-list">
                  {detail.explanation.map((e, i) => (
                    <li key={i}>
                      {e.contribution > 0 ? "↑" : "↓"} <strong>{friendlyFeature(e.feature)}</strong> — {strength(e.contribution)} factor
                      that {e.contribution > 0 ? "improves" : "hurts"} the chances of recovery
                    </li>
                  ))}
                </ul>
              </div>
              <div className="card">
                <p><strong>What we did:</strong> {ACTION_LABEL[detail.decision.action] || detail.decision.action}
                  {detail.decision.channel ? ` via ${detail.decision.channel.replace(/_/g, " ")}` : ""}</p>
                <p><strong>Estimated cost:</strong> ₹{detail.decision.cost.toFixed(2)}</p>
                <strong>Why:</strong>
                <ul className="reasoning-list">
                  {detail.decision.reasoning.map((r, i) => <li key={i}>{displayReasoning(r)}</li>)}
                </ul>
                {detail.promise_to_pay && (
                  <p>
                    <strong>Promise to pay:</strong> {detail.promise_to_pay.status === "kept" ? "✅" : "🚨"} {detail.promise_to_pay.note}
                  </p>
                )}
                {detail.message && (
                  <>
                    <strong>Message sent to the customer:</strong>
                    <div style={{ background: "#eaf1fc", padding: "10px 12px", borderRadius: 8, marginTop: 6, fontSize: "0.88rem" }}>
                      {detail.message}
                    </div>
                  </>
                )}
              </div>
          </div>

          <div className="card" style={{ marginTop: 16 }}>
              <button className="btn secondary" onClick={() => setShowTechnical(!showTechnical)}>
                {"🔧"} {showTechnical ? "Hide" : "Show"} technical details
              </button>
              {showTechnical && (
                <div style={{ marginTop: 12, fontSize: "0.85rem" }}>
                  <strong>Raw model feature contributions:</strong>
                  <ul className="reasoning-list">
                    {detail.full_explanation.map((e, i) => (
                      <li key={i}><code>{e.feature}</code> — {e.contribution > 0 ? "increases" : "decreases"} recoverability ({e.contribution >= 0 ? "+" : ""}{e.contribution.toFixed(2)})</li>
                    ))}
                  </ul>
                  {detail.razorpay_call && (
                    <>
                      <strong>Razorpay API call this would trigger:</strong>
                      <pre style={{ background: "#f4f6f9", padding: 10, borderRadius: 8, overflowX: "auto" }}>
                        {detail.razorpay_call.method} {detail.razorpay_call.path}
                        {"\n"}{JSON.stringify(detail.razorpay_call.payload, null, 2)}
                      </pre>
                      <p style={{ color: "var(--ink-muted)" }}>{detail.razorpay_call.note}</p>
                    </>
                  )}
                  <strong>Full audit trail:</strong>
                  <table className="data-table">
                    <thead><tr><th>Time</th><th>Action</th><th>Reasoning</th></tr></thead>
                    <tbody>
                      {detail.audit_trail.map((a, i) => (
                        <tr key={i}><td>{a.timestamp}</td><td>{a.action}</td><td>{(a.reasoning || []).join(" ")}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </div>
        </div>
      )}

      {selectedId && !detail && <div className="loading-state" style={{ marginTop: 20 }}>Loading…</div>}
    </div>
  );
}

// Reshapes a /dashboard/live-transactions entry into the same row shape
// the synthetic table already uses, so both can render in one table --
// tagged with _source/_liveEntry so a click knows how to show detail
// without a second, incompatible API call.
function normalizeLiveRow(entry) {
  return {
    transaction_id: entry.transaction_id,
    risk_type: "payment_failure",
    failure_reason: entry.failure_reason,
    amount: entry.amount,
    customer_segment: entry.customer_segment || "unknown",
    recoverability_score: entry.recoverability_score,
    agent_action: entry.action,
    agent_resolved: false, // real recovery status lives on the Live tab's own polling; kept simple here
    intervention_cost: entry.intervention_cost,
    _source: "live",
    _liveEntry: entry,
  };
}
