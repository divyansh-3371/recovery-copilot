# 5-minute pitch script — Recovery Copilot

Timing is a guide, not a script to read verbatim — say it in your own words.

## 0:00–0:25 — Hook

> "Revenue loss at a payments company almost never happens in one clean
> step — a payment fails, a checkout gets abandoned, a subscription
> mandate breaks, an invoice goes overdue. Most systems log it and stop.
> I built Recovery Copilot: an agent that detects the risk, figures out
> why, picks the right intervention, executes it for real, and proves
> the money it recovered."

## 0:25–0:50 — What it is

> "It's a Python agent — a trained recoverability model scores every
> at-risk transaction, a root-cause detector catches infrastructure
> outages before blaming the customer, a policy engine picks one of six
> bounded actions under strict compliance stopping rules, and — this is
> the part most buildathon projects don't get to — it's connected to a
> real, live Razorpay account, executing real recovery actions."

## 0:50–1:50 — Dashboard tab

> "This is the Dashboard, running on a batch of transactions." [Point at
> hero number] "This period it recovered ₹X out of ₹Y at risk." [Point at
> Heads up card] "It just caught a netbanking outage on its own — 37x
> normal — and paused retries instead of spamming customers during a
> bank-side problem." [Point at charts] "Recovered by category vs. a
> naive approach, and what's actually happening operationally — click a
> bar, see a real example."

## 1:50–2:30 — Transactions + Try a transaction

> "Every decision is explainable —" [open a transaction] "here's Recovery
> Copilot's confidence, in plain language, and exactly what it did and
> why." [Switch to Try a transaction] "And this isn't canned — change the
> amount live" [drag it past ₹75,000] "— watch it flip straight to a
> specialist, regardless of the usual reason-based routing."

## 2:30–4:30 — Live tab (the centerpiece)

> "Here's what makes this real, not a demo. This is a live, connected
> Razorpay account — Test Mode, so no real money moves, but every other
> part of this is genuine."
> [Open Live tab, show the embedded checkout] "I'll make a real payment
> and fail it on purpose." [Pick a customer type, pay with a real
> Razorpay test failure card]
> "The moment that fails, Razorpay's own servers call my webhook
> directly — no polling, no human — and the exact same model and policy
> engine that scored the batch scores this, in real time." [Point at the
> decision appearing]
> "And it doesn't stop at a label —" [point at execution result] "it
> actually creates a real, payable Razorpay Payment Link, or sends a real
> email to the customer, right now." [Show the 'Recovered so far' KPI]
> "And if that link gets paid, this dashboard tracks the real recovered
> amount, live, against Razorpay's own API — not a simulated number."

## 4:30–4:50 — Why this is more than a script

> "Three things make this a real system: the recoverability score comes
> from an actual trained model, fully explainable per transaction. The
> root-cause detector separates a bank outage from a customer problem
> before anything else decides. And the stopping rules — do-not-contact,
> attempt caps, an economical-amount floor — are checked before any
> customer-facing action, every time, with a full audit trail."

## 4:50–5:00 — Close

> "Recovery Copilot: detect, diagnose, decide, execute, prove —
> connected to a real payment gateway, executing real recovery actions,
> not just describing what it would do. That's AI Revenue Recovery,
> actually recovering revenue."

---

## Recording checklist

- [ ] `uvicorn api:app --port 8010` running, with `.env` loaded
      (Razorpay + Resend configured)
- [ ] `ngrok http 8010` running, webhook URL registered in the Razorpay
      dashboard matches the current tunnel URL
- [ ] `cd frontend && npm run dev` running, dashboard open at
      `localhost:5173`
- [ ] Pick a batch seed in advance that shows a systemic issue banner
      (default seed 42 does)
- [ ] Have a Razorpay test failure card ready
      (`4100 2800 0006 0003` — card declined)
- [ ] Do one practice run of the Live tab flow before recording for real
      — payment → webhook → decision → execution can take a few seconds
- [ ] Screen + voice recording, ~5 minutes, upload and paste the link
      into the submission form
