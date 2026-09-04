import { useEffect, useState } from "react";
import { api } from "../api";
import { ACTION_LABEL, RISK_TYPE_LABEL, humanize, formatMoney, displayReasoning, friendlyFeature, strength } from "../labels";

export default function TransactionsTab({ seed }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ risk_type: "", agent_action: "", customer_segment: "" });
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showTechnical, setShowTechnical] = useState(false);

  useEffect(() => {
    setRows(null);
    setSelectedId(null);
    setDetail(null);
    const params = {};
    if (filters.risk_type) params.risk_type = filters.risk_type;
    if (filters.agent_action) params.action = filters.agent_action;
    if (filters.customer_segment) params.customer_segment = filters.customer_segment;
    api.transactions(seed, params).then((d) => setRows(d.transactions)).catch((e) => setError(e.message));
  }, [seed, filters]);

  useEffect(() => {
    if (!selectedId) return;
    setDetail(null);
    api.transactionDetail(selectedId, seed).then(setDetail).catch((e) => setError(e.message));
  }, [selectedId, seed]);

  if (error) return <div className="empty-state">Couldn't load transactions: {error}</div>;

  const riskTypes = [...new Set((rows || []).map((r) => r.risk_type))];
  const actions = [...new Set((rows || []).map((r) => r.agent_action))];
  const segments = [...new Set((rows || []).map((r) => r.customer_segment))];

  return (
    <div>
      <h2>All transactions</h2>
      <p style={{ color: "var(--ink-secondary)" }}>Every payment issue Recovery Copilot has handled this period.</p>

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
                <th>Transaction</th><th>Issue</th><th>Reason</th><th>Amount</th>
                <th>Customer</th><th>Confidence</th><th>Action</th><th>Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.transaction_id} onClick={() => setSelectedId(r.transaction_id)}>
                  <td><code>{r.transaction_id}</code></td>
                  <td>{RISK_TYPE_LABEL[r.risk_type] || r.risk_type}</td>
                  <td>{humanize(r.failure_reason)}</td>
                  <td>{formatMoney(r.amount)}</td>
                  <td>{humanize(r.customer_segment)}</td>
                  <td>{Math.round(r.recoverability_score * 100)}%</td>
                  <td>{ACTION_LABEL[r.agent_action] || r.agent_action}</td>
                  <td>{r.agent_resolved ? "✅ Recovered" : "In progress"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && (
        <div style={{ marginTop: 20 }}>
          <h3>Transaction detail</h3>
          {!detail ? (
            <div className="loading-state">Loading…</div>
          ) : (
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
          )}

          {detail && (
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
          )}
        </div>
      )}
    </div>
  );
}
