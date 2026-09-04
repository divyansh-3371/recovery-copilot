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

// FastAPI's error body isn't always a plain string: a Pydantic validation
// failure (422) sends `detail` as an array of {loc, msg, type} objects,
// which would otherwise print as the useless "[object Object]" once
// coerced into a template string. A manually-raised HTTPException (401,
// 404, 503...) sends `detail` as a plain string, which passes through
// unchanged.
function formatErrorDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc.filter((p) => p !== "body").join(".") : "";
        return field ? `${field}: ${e.msg}` : e.msg;
      })
      .join("; ");
  }
  return null;
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
      detail = formatErrorDetail(body.detail) || JSON.stringify(body);
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
  recoveryStatus: (paymentId) => request(`/checkout/recovery-status/${paymentId}`),
};
