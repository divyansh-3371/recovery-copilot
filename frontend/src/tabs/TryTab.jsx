import { useEffect, useState } from "react";
import { api } from "../api";
import { ACTION_LABEL, RISK_TYPE_LABEL, humanize, displayReasoning, friendlyFeature, strength, actionColor } from "../labels";

const DEFAULTS = {
  risk_type: "payment_failure",
  failure_reason: "insufficient_funds",
  amount: 5000,
  payment_method: "card",
  customer_segment: "returning",
  previous_attempts: 0,
  customer_local_hour: 12,
  do_not_contact: false,
};

export default function TryTab() {
  const [options, setOptions] = useState(null);
  const [form, setForm] = useState(DEFAULTS);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showTechnical, setShowTechnical] = useState(false);

  useEffect(() => {
    api.options().then(setOptions).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!options) return;
    api.tryTransaction(form).then(setResult).catch((e) => setError(e.message));
  }, [form, options]);

  function update(field, value) {
    setForm((f) => {
      const next = { ...f, [field]: value };
      if (field === "risk_type") {
        next.failure_reason = options.failure_reasons[value][0];
      }
      return next;
    });
  }

  if (error) return <div className="empty-state">Couldn't load: {error}</div>;
  if (!options) return <div className="loading-state">Loading…</div>;

  return (
    <div>
      <h2>See how Recovery Copilot handles a case</h2>
      <p style={{ color: "var(--ink-secondary)" }}>Fill in the details and watch the decision recompute instantly.</p>

      <div className="grid-3">
        <div>
          <label className="field-label">Issue type</label>
          <select value={form.risk_type} onChange={(e) => update("risk_type", e.target.value)}>
            {options.risk_types.map((r) => <option key={r} value={r}>{RISK_TYPE_LABEL[r] || r}</option>)}
          </select>
          <label className="field-label" style={{ marginTop: 10 }}>Reason</label>
          <select value={form.failure_reason} onChange={(e) => update("failure_reason", e.target.value)}>
            {options.failure_reasons[form.risk_type].map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
          </select>
          <label className="field-label" style={{ marginTop: 10 }}>Amount (₹)</label>
          <input type="number" min={50} value={form.amount} onChange={(e) => update("amount", Number(e.target.value))} />
        </div>
        <div>
          <label className="field-label">Payment method</label>
          <select value={form.payment_method} onChange={(e) => update("payment_method", e.target.value)}>
            {options.payment_methods.map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
          </select>
          <label className="field-label" style={{ marginTop: 10 }}>Customer type</label>
          <select value={form.customer_segment} onChange={(e) => update("customer_segment", e.target.value)}>
            {options.customer_segments.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
          <label className="field-label" style={{ marginTop: 10 }}>Times already tried: {form.previous_attempts}</label>
          <input type="range" min={0} max={4} value={form.previous_attempts} onChange={(e) => update("previous_attempts", Number(e.target.value))} />
        </div>
        <div>
          <label className="field-label">Customer's local hour: {form.customer_local_hour}</label>
          <input type="range" min={0} max={23} value={form.customer_local_hour} onChange={(e) => update("customer_local_hour", Number(e.target.value))} />
          <label style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 12, fontSize: "0.88rem" }}>
            <input type="checkbox" checked={form.do_not_contact} onChange={(e) => update("do_not_contact", e.target.checked)} style={{ width: "auto" }} />
            Customer has opted out of contact
          </label>
          <p style={{ fontSize: "0.78rem", color: "var(--ink-muted)", marginTop: 10 }}>
            Tip: try 3+ attempts to see it stop on its own, or push amount past ₹75,000 to see it go straight to a specialist.
          </p>
        </div>
      </div>

      {result && (
        <>
          <div className="grid-2" style={{ marginTop: 20 }}>
            <div className="card">
              <h3>Confidence: {Math.round(result.score * 100)}%</h3>
              <div style={{ height: 8, background: "var(--grid)", borderRadius: 4, overflow: "hidden", marginBottom: 12 }}>
                <div style={{ height: "100%", width: `${Math.min(Math.max(result.score, 0), 1) * 100}%`, background: "var(--blue)" }} />
              </div>
              <strong>Why we think this:</strong>
              <ul className="reasoning-list">
                {result.explanation.map((e, i) => (
                  <li key={i}>
                    {e.contribution > 0 ? "↑" : "↓"} <strong>{friendlyFeature(e.feature)}</strong> — {strength(e.contribution)} factor
                    that {e.contribution > 0 ? "improves" : "hurts"} the chances of recovery
                  </li>
                ))}
              </ul>
            </div>
            <div className="card">
              <h3 style={{ color: actionColor(result.decision.action) }}>
                {ACTION_LABEL[result.decision.action] || result.decision.action}
                {result.decision.channel ? ` via ${result.decision.channel.replace(/_/g, " ")}` : ""}
              </h3>
              <p><strong>Estimated cost:</strong> ₹{result.decision.cost.toFixed(2)}</p>
              <strong>Why:</strong>
              <ul className="reasoning-list">
                {result.decision.reasoning.map((r, i) => <li key={i}>{displayReasoning(r)}</li>)}
              </ul>
            </div>
          </div>

          {result.message && (
            <div style={{ marginTop: 16 }}>
              <strong>Message that would be sent:</strong>
              <div style={{ background: "#eaf1fc", padding: "10px 12px", borderRadius: 8, marginTop: 6, fontSize: "0.88rem" }}>
                {result.message}
              </div>
            </div>
          )}

          <div className="card" style={{ marginTop: 16 }}>
            <button className="btn secondary" onClick={() => setShowTechnical(!showTechnical)}>
              {"🔧"} {showTechnical ? "Hide" : "Show"} technical details
            </button>
            {showTechnical && (
              <div style={{ marginTop: 12, fontSize: "0.85rem" }}>
                {result.decision.retry_method && (
                  <p><strong>Retry sequencer:</strong> <code>{result.decision.retry_method}</code> method, in {result.decision.retry_delay_hours}h</p>
                )}
                <strong>Raw model feature contributions:</strong>
                <ul className="reasoning-list">
                  {result.full_explanation.map((e, i) => (
                    <li key={i}><code>{e.feature}</code> — {e.contribution > 0 ? "increases" : "decreases"} recoverability ({e.contribution >= 0 ? "+" : ""}{e.contribution.toFixed(2)})</li>
                  ))}
                </ul>
                {result.razorpay_call && (
                  <>
                    <strong>Razorpay API call this would trigger:</strong>
                    <pre style={{ background: "#f4f6f9", padding: 10, borderRadius: 8, overflowX: "auto" }}>
                      {result.razorpay_call.method} {result.razorpay_call.path}
                      {"\n"}{JSON.stringify(result.razorpay_call.payload, null, 2)}
                    </pre>
                  </>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
