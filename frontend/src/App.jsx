import { useEffect, useState } from "react";
import { getApiBase, setApiBase, api } from "./api";
import DashboardTab from "./tabs/DashboardTab";
import TransactionsTab from "./tabs/TransactionsTab";
import TimelineTab from "./tabs/TimelineTab";
import TryTab from "./tabs/TryTab";
import LiveTab from "./tabs/LiveTab";

const TABS = [
  { key: "dashboard", icon: "\u{1F3E0}", label: "Dashboard" },
  { key: "transactions", icon: "\u{1F4CB}", label: "Transactions" },
  { key: "timeline", icon: "\u{1F5D3}️", label: "Recovery timeline" },
  { key: "try", icon: "\u{1F9EA}", label: "Try a transaction" },
  { key: "live", icon: "\u{1F534}", label: "Live" },
];

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [seed, setSeed] = useState(42);
  const [apiBase, setApiBaseState] = useState(getApiBase());
  const [apiOk, setApiOk] = useState(null);

  useEffect(() => {
    api.health().then(() => setApiOk(true)).catch(() => setApiOk(false));
  }, [apiBase]);

  function handleApiBaseChange(value) {
    setApiBase(value);
    setApiBaseState(value);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1>{"\u{1F4B8}"} Recovery Copilot</h1>
        <div className="caption">Automatic payment recovery</div>

        <nav className="nav-list">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`nav-item ${tab === t.key ? "active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              <span>{t.icon}</span> {t.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-dataset">
          <label className="field-label">Sample dataset</label>
          <input
            type="number" min={1} max={9999} value={seed}
            onChange={(e) => setSeed(Number(e.target.value) || 1)}
          />
        </div>

        <details style={{ fontSize: "0.82rem", color: "var(--ink-secondary)" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>{"ℹ️"} About</summary>
          <p style={{ marginTop: 8 }}>
            Recovery Copilot automatically detects payment issues -- failed payments, abandoned
            checkouts, failed subscriptions, and overdue invoices -- figures out the most likely
            reason, and takes the right action to recover the money.
          </p>
          <details style={{ marginTop: 10 }}>
            <summary style={{ cursor: "pointer" }}>Advanced</summary>
            <label className="field-label" style={{ marginTop: 8 }}>API service URL</label>
            <input
              type="text" value={apiBase}
              onChange={(e) => handleApiBaseChange(e.target.value)}
            />
          </details>
        </details>
      </aside>

      <main className="main">
        {apiOk === false && (
          <div className="status-box error" style={{ marginBottom: 16 }}>
            Can't reach the backend right now -- check with support if this doesn't clear up.
          </div>
        )}
        {tab === "dashboard" && <DashboardTab seed={seed} />}
        {tab === "transactions" && <TransactionsTab seed={seed} />}
        {tab === "timeline" && <TimelineTab seed={seed} />}
        {tab === "try" && <TryTab />}
        {tab === "live" && <LiveTab apiBase={apiBase} />}
      </main>
    </div>
  );
}
