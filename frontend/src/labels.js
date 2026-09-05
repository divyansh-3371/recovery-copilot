// Plain-language labels for everything the backend refers to by its
// internal name -- mirrors agent/app.py's ACTION_LABEL / RISK_TYPE_LABEL /
// SYSTEMIC_REASON_PHRASE dicts so the two frontends stay in sync.

export const ACTION_LABEL = {
  SEND_MESSAGE: "Sent a reminder",
  RETRY_PAYMENT: "Retried the payment",
  ESCALATE_HUMAN: "Sent to a specialist",
  ESCALATE_COLLECTIONS: "Sent to collections/legal",
  ESCALATE_OPS: "Flagged as a system issue",
  STOP: "Left alone (not worth pursuing)",
};

export const RISK_TYPE_LABEL = {
  payment_failure: "Payment failure",
  checkout_abandonment: "Checkout drop-off",
  subscription_failure: "Subscription failure",
  invoice_overdue: "Overdue invoice",
};

export const SYSTEMIC_REASON_PHRASE = {
  bank_timeout: "timing out",
  network_drop: "dropping mid-payment",
  mandate_bank_error: "erroring on auto-pay charges",
  issuer_declined: "being declined by the bank",
};

export const ACTION_COLOR = {
  STOP: "var(--status-critical)",
};
const DEFAULT_ACTION_COLOR = "var(--status-good)";
export function actionColor(action) {
  return ACTION_COLOR[action] || DEFAULT_ACTION_COLOR;
}

export function humanize(text) {
  if (!text) return "";
  const s = text.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatMoney(amount) {
  const n = Number(amount) || 0;
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

// Lightly cleans a policy-engine reasoning string for display, mirroring
// app.py's display_reasoning(): a raw score becomes a percentage, quoted
// identifiers and snake_case tokens get their underscores turned to spaces.
export function displayReasoning(text) {
  if (!text) return "";
  let out = text.replace(
    /[Rr]ecoverability score \(?(\d+\.\d+)\)?/,
    (_, p1) => `Confidence (${Math.round(parseFloat(p1) * 100)}%)`
  );
  out = out.replace(/'([a-z0-9_]+)'/g, (_, p1) => p1.replace(/_/g, " "));
  out = out.replace(/\b([a-z]+_[a-z_]+)\b/g, (_, p1) => p1.replace(/_/g, " "));
  return out;
}

// A one-line version of the (cleaned) reasoning for the primary view --
// the full, precise text stays available behind a "Show more" toggle
// rather than being hidden entirely or dumped in full by default.
export function shortReason(reasoning) {
  if (!Array.isArray(reasoning) || reasoning.length === 0) return "";
  const cleaned = displayReasoning(reasoning[0]);
  const cut = Math.min(
    ...[". ", " — ", ": "].map((sep) => { const i = cleaned.indexOf(sep); return i === -1 ? Infinity : i; })
  );
  if (cut === Infinity || cut > 80) {
    return cleaned.length > 90 ? cleaned.slice(0, 87) + "…" : cleaned;
  }
  return cleaned.slice(0, cut) + "…";
}

export function friendlyFeature(feat) {
  const name = feat.includes("__") ? feat.split("__").slice(1).join("__") : feat;
  const numeric = {
    previous_attempts: "how many times we've already tried",
    amount_log: "the transaction amount",
    days_since_event: "how long ago this happened",
    customer_local_hour: "time of day",
    do_not_contact_flag: "contact preference",
  };
  if (numeric[name]) return numeric[name];
  const prefixes = {
    "risk_type_": "issue type",
    "failure_reason_": "reason",
    "payment_method_": "payment method",
    "customer_segment_": "customer type",
  };
  for (const [prefix, label] of Object.entries(prefixes)) {
    if (name.startsWith(prefix)) {
      return `${label}: ${name.slice(prefix.length).replace(/_/g, " ")}`;
    }
  }
  return name.replace(/_/g, " ");
}

export function strength(contrib) {
  const a = Math.abs(contrib);
  if (a >= 0.35) return "a strong";
  if (a >= 0.15) return "a moderate";
  return "a slight";
}
