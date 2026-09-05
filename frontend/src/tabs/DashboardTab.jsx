import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell,
} from "recharts";
import { api } from "../api";
import { ACTION_LABEL, RISK_TYPE_LABEL, SYSTEMIC_REASON_PHRASE, humanize, formatMoney } from "../labels";

export default function DashboardTab({ seed }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [clickedAction, setClickedAction] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    setClickedAction(null);
    api.summary(seed).then(setData).catch((e) => setError(e.message));
  }, [seed]);

  if (error) return <div className="empty-state">Couldn't load the dashboard: {error}</div>;
  if (!data) return <div className="loading-state">Loading your transactions…</div>;

  const { summary, systemic_issues, category_breakdown, action_breakdown, top_reasons, in_progress } = data;

  const categoryChartData = category_breakdown.map((c) => ({
    name: RISK_TYPE_LABEL[c.risk_type] || c.risk_type,
    "A simple retry-everyone approach": c.baseline_recovered_amount,
    "Recovery Copilot": c.agent_recovered_amount,
  }));

  const actionChartData = [...action_breakdown]
    .sort((a, b) => a.count - b.count)
    .map((a) => ({ name: ACTION_LABEL[a.action] || a.action, count: a.count, action: a.action, example: a.example_transaction_id }));

  const reasonChartData = top_reasons.map((r) => ({ name: humanize(r.failure_reason), amount: r.amount }));

  const example = clickedAction && action_breakdown.find((a) => a.action === clickedAction);

  return (
    <div>
      <h2>This period, Recovery Copilot recovered <strong>{formatMoney(summary.agent_net_recovered)}</strong> for you</h2>
      <p style={{ color: "var(--ink-secondary)" }}>
        out of {formatMoney(summary.total_at_risk)} at risk across {summary.n_transactions} transactions — {" "}
        <strong>{summary.agent_recovery_rate.toFixed(0)}%</strong> recovered, automatically.
      </p>

      <div className="card" style={{ margin: "16px 0" }}>
        {systemic_issues.length > 0 ? (
          <>
            <h4>{"⚠️"} Heads up</h4>
            {systemic_issues.map((issue, i) => {
              const phrase = SYSTEMIC_REASON_PHRASE[issue.failure_reason] || humanize(issue.failure_reason).toLowerCase();
              return (
                <p key={i} style={{ margin: "6px 0" }}>
                  Your <strong>{issue.payment_method}</strong> payments are <strong>{phrase}</strong> more than usual right now
                  {" "}({issue.ratio.toFixed(0)}x normal) — this looks like a bank/gateway issue, not your customers.
                  We've paused retries for these and alerted your ops team.
                </p>
              );
            })}
          </>
        ) : (
          <>
            <h4>{"✅"} Everything looks normal</h4>
            <span style={{ color: "var(--ink-muted)" }}>No unusual payment patterns detected right now.</span>
          </>
        )}
      </div>

      <div className="kpi-row" style={{ marginBottom: 20 }}>
        <div className="kpi">
          <div className="label">Total at risk</div>
          <div className="value">{formatMoney(summary.total_at_risk)}</div>
        </div>
        <div className="kpi">
          <div className="label">Recovered</div>
          <div className="value">{formatMoney(summary.agent_net_recovered)}</div>
          <div className="delta">+{formatMoney(summary.net_uplift_amount)} vs. before</div>
        </div>
        <div className="kpi">
          <div className="label">Recovery rate</div>
          <div className="value">{summary.agent_recovery_rate.toFixed(0)}%</div>
        </div>
        <div className="kpi">
          <div className="label">Spent recovering it</div>
          <div className="value">{formatMoney(summary.agent_intervention_cost)}</div>
          {summary.agent_recovered > 0 && (
            <div className="delta" style={{ color: "var(--ink-muted)" }}>
              {((summary.agent_intervention_cost / summary.agent_recovered) * 100).toFixed(1)}% of what came back
            </div>
          )}
        </div>
        <div className="kpi">
          <div className="label">Currently in progress</div>
          <div className="value">{in_progress}</div>
        </div>
      </div>

      <p style={{ color: "var(--ink-secondary)", fontSize: "0.88rem" }}>
        This also means <strong>{summary.baseline_compliance_violations_avoided}</strong> customers were protected
        from unnecessary contact, and <strong>{summary.promises_kept} of {summary.promises_kept + summary.promises_broken}</strong>{" "}
        payment promises were kept.
      </p>

      <div className="grid-2" style={{ marginTop: 20 }}>
        <div>
          <h3>Recovered, by category</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={categoryChartData} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid stroke="var(--grid)" horizontal={false} />
              <XAxis type="number" tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} />
              <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v) => formatMoney(v)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="A simple retry-everyone approach" fill="var(--blue-light)" />
              <Bar dataKey="Recovery Copilot" fill="var(--blue)" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div>
          <h3>What's happening</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={actionChartData} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid stroke="var(--grid)" horizontal={false} />
              <XAxis type="number" />
              <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar
                dataKey="count" fill="var(--blue)" cursor="pointer"
                onClick={(d) => setClickedAction(d.action)}
              >
                {actionChartData.map((d, i) => <Cell key={i} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          {example ? (
            <p style={{ fontSize: "0.85rem", background: "#eaf1fc", padding: "10px 12px", borderRadius: 8 }}>
              <strong>Example — {ACTION_LABEL[example.action] || example.action}:</strong> look it up on the
              {" "}<strong>Transactions</strong> tab (ID <code>{example.example_transaction_id}</code>).
            </p>
          ) : (
            <p style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>Click a bar to see a real example of that decision.</p>
          )}
        </div>
      </div>

      <div style={{ marginTop: 24 }}>
        <h3>Where you're losing the most money right now</h3>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={reasonChartData} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid stroke="var(--grid)" horizontal={false} />
            <XAxis type="number" tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} />
            <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 12 }} />
            <Tooltip formatter={(v) => formatMoney(v)} />
            <Bar dataKey="amount" fill="var(--orange)" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
