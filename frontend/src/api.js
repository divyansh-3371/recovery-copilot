// Thin fetch wrapper over the FastAPI backend (api.py + dashboard_api.py).
// Base URL is configurable at runtime (stored in localStorage) since the
// API service might run on a different port than the default -- there's no
// build-time env var to change without a rebuild otherwise.

const DEFAULT_BASE = "http://localhost:8010";

export function getApiBase() {
  return localStorage.getItem("rc_api_base") || DEFAULT_BASE;
}

export function setApiBase(url) {
  localStorage.setItem("rc_api_base", url.replace(/\/$/, ""));
}

async function request(path, options = {}) {
  const base = getApiBase();
  const resp = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json();
}

export const api = {
  health: () => request("/health"),
  razorpayStatus: () => request("/razorpay/status"),
  options: () => request("/dashboard/options"),
  summary: (seed) => request(`/dashboard/summary?seed=${seed}`),
  transactions: (seed, filters = {}) => {
    const params = new URLSearchParams({ seed, ...filters });
    return request(`/dashboard/transactions?${params}`);
  },
  transactionDetail: (id, seed) => request(`/dashboard/transaction/${id}?seed=${seed}`),
  timeline: (seed, days) => request(`/dashboard/timeline?seed=${seed}&days=${days}`),
  tryTransaction: (body) => request("/dashboard/try", { method: "POST", body: JSON.stringify(body) }),
  liveTransactions: () => request("/dashboard/live-transactions"),
  checkoutDecision: (paymentId) => request(`/checkout/decision/${paymentId}`),
};
