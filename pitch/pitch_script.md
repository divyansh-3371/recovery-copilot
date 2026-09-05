# 5-minute pitch script — Recovery Copilot

Timing is a guide, not a script to read verbatim — say it in your own words.
Pace is tight this version (it now explains the charts and the confidence
score explicitly, not just points at them) — do the practice run below
before recording for real.

## 0:00–0:20 — Hook

> "Revenue loss at a payments company almost never happens in one clean
> step — a payment fails, a checkout gets abandoned, a subscription
> mandate breaks, an invoice goes overdue. Most systems log it and stop.
> I built Recovery Copilot: an agent that detects the risk, figures out
> why, picks the right intervention, executes it for real, and proves
> the money it recovered — and what it cost to recover it."

## 0:20–1:00 — What it is, and where "confidence" actually comes from

> "It's a Python agent behind a React dashboard — no Streamlit, this is a
> real app talking to a real API. Every transaction gets a recoverability
> score from a trained logistic regression — it takes the failure reason,
> payment method, customer segment, the amount, days since it happened,
> even the customer's local hour, and outputs a probability of recovery.
> That's the 'confidence' percentage you'll see on every transaction —
> it's not a made-up number, it's a real model's output, and I'll show you
> its actual feature-by-feature reasoning in a minute. A root-cause
> detector catches infrastructure outages before blaming the customer, and
> a policy engine picks one of six bounded actions under strict compliance
> stopping rules — and, the part most buildathon projects don't get to,
> it's connected to a real, live Razorpay account, executing real
> recovery actions against it."

## 1:00–1:50 — Dashboard tab: the charts

*(Stay on Dashboard.)*

> "This period it recovered ₹X out of ₹Y at risk." *[point at the KPI
> row]* "Recovered, recovery rate, and 'Spent recovering it' — every
> action has a real modeled cost, so this is net proof, not gross
> recovered hiding an expensive way of getting there." *[point at Heads
> up]* "It just caught a netbanking outage on its own, 37x normal, and
> paused retries instead of spamming customers during a bank-side
> problem."
> *[point at "Recovered, by category"]* "This chart is the actual case for
> the project: the light bar is what a naive 'retry everyone the same
> way' baseline would recover, the dark bar is what Recovery Copilot
> recovers, per issue type — same transactions, two strategies."
> *[point at "What's happening"]* "This is every action the agent took,
> as a count — click a bar" *[click one]* "and it jumps to a real example
> transaction on the Transactions tab, not a made-up one."
> *[scroll down to "Where you're losing the most money"]* "And this is
> sorted by ₹ at risk, not by count — it's where a merchant should
> actually look first, since the most common failure reason isn't
> always the most expensive one."

## 1:50–2:30 — Transactions: reading the confidence score for real

*(Click a row → open detail → click "Show technical details".)*

> "Here's a real transaction's confidence, in plain language, and exactly
> what it did and why." *[click Show technical details]* "And here's the
> actual model output behind that number — the real feature contributions,
> not a summary. Customer type, payment method, the amount — each one
> pushing the score up or down, and the sign and size here is exactly what
> the logistic regression computed, nothing hand-written."

## 2:30–3:00 — Try a transaction: it's live, not canned

*(Switch tabs, drag the amount past ₹75,000, then set customer type to New.)*

> "This isn't canned — change the amount live" *[drag past ₹75,000]* "and
> it flips straight to a specialist. Or take a new customer at a low
> score" *[set customer type to New]* "— a returning customer here gets
> left alone, but a merchant already paid to acquire this one, so the
> agent still sends a cheap nudge instead of writing them off."

## 3:00–4:30 — Live tab (the centerpiece)

*(Switch to Live tab → open "Make a real transaction" → pick a customer type → pay with the test failure card.)*

> "Here's what makes this real, not a demo. This is a live, connected
> Razorpay account — Test Mode, so no real money moves, but everything
> else here is genuine. I'll make a real payment and fail it on purpose."
> *[pay with the declined card]*
> "The moment that fails, Razorpay's own servers call my webhook directly
> — no polling, no human — and the same model scores this, in real time,
> right on the checkout page the customer is still looking at." *[point
> at the decision box and Pay now button]* "It doesn't stop at a label —
> it creates a real, payable Payment Link and emails it immediately,
> because this is the customer responding to their own failed payment,
> not me reaching out unprompted." *[scroll to Live entries]* "Cost to
> recover, right next to confidence. And if a customer fails, gets this
> link, and fails again, that shows up as one purchase attempted twice,
> not two separate ones inflating what's at risk."

## 4:30–5:00 — Close

> "Three things make this real, not a script: the confidence score is an
> actual trained model, explainable feature by feature. The stopping
> rules — do-not-contact, quiet hours, attempt caps — are checked before
> any customer-facing action, every time. And it's connected to a real
> payment gateway, executing real recovery actions, accounting for what
> they cost, not just describing what it would do. That's AI Revenue
> Recovery, actually recovering revenue."

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
- [ ] On Transactions, know which real transaction you'll open and its
      "Show technical details" feature list before recording, so you're
      not hunting for one live
- [ ] On Try a transaction, know the two moves cold: amount > ₹75,000
      (value-triage escalation), and a New customer at a low score
      (sunk-cost nudge instead of a stop)
- [ ] Do one full practice run of the Live tab flow before recording for
      real — payment → webhook → decision → execution can take a few
      seconds; if quiet hours happen to be active locally, say so on
      camera rather than let a held-back email look like a bug
- [ ] This version covers more ground in the same 5 minutes — do at
      least one timed practice pass and trim narration (not content) if
      you're running long, rather than cutting the charts/confidence
      explanation back out
- [ ] Screen + voice recording, ~5 minutes, upload (YouTube unlisted or a
      link-shared Drive file both work) and paste the link into the
      submission form
