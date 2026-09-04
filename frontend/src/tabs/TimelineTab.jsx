import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from "recharts";
import { api } from "../api";
import { formatMoney } from "../labels";

export default function TimelineTab({ seed }) {
  const [days, setDays] = useState(5);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    api.timeline(seed, days).then((d) => setData(d.days)).catch((e) => setError(e.message));
  }, [seed, days]);

  if (error) return <div className="empty-state">Couldn't load the timeline: {error}</div>;

  return (
    <div>
      <h2>Recovery over time</h2>
      <p style={{ color: "var(--ink-secondary)" }}>
        The Dashboard shows one snapshot. This shows what happens over several days as Recovery Copilot follows up.
      </p>

      <label className="field-label">Number of days to simulate</label>
      <input
        type="range" min={2} max={10} value={days}
        onChange={(e) => setDays(Number(e.target.value))}
        style={{ width: 260 }}
      />
      <span style={{ marginLeft: 10 }}>{days} days</span>

      {!data ? (
        <div className="loading-state">Simulating the recovery timeline…</div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={300} style={{ marginTop: 20 }}>
            <AreaChart data={data}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d) => `Day ${d}`} />
              <YAxis tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} />
              <Tooltip formatter={(v) => formatMoney(v)} labelFormatter={(d) => `Day ${d}`} />
              <Area type="monotone" dataKey="cumulative_recovered" stroke="var(--blue)" fill="rgba(42,120,214,0.08)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>

          {data.length > 0 && (
            <div className="card" style={{ marginTop: 16 }}>
              <p>
                By day <strong>{data[data.length - 1].day}</strong>: <strong>{data[data.length - 1].cumulative_resolved}</strong>{" "}
                transactions resolved, <strong>{formatMoney(data[data.length - 1].cumulative_recovered)}</strong> recovered.
              </p>
            </div>
          )}

          <details style={{ marginTop: 16 }}>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>Day-by-day breakdown</summary>
            <table className="data-table" style={{ marginTop: 8 }}>
              <thead>
                <tr><th>Day</th><th>Resolved that day</th><th>Recovered that day</th><th>Total resolved</th><th>Total recovered</th></tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.day}>
                    <td>{d.day}</td><td>{d.resolved_today}</td><td>{formatMoney(d.recovered_today)}</td>
                    <td>{d.cumulative_resolved}</td><td>{formatMoney(d.cumulative_recovered)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </div>
  );
}
