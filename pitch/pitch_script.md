# 5-minute pitch script — Recovery Copilot

Timing is a guide, not a script to read verbatim — say it in your own words.

## 0:00–0:20 — Hook

> "Revenue loss at a payments company almost never happens in one clean
> step — a payment fails, a checkout gets abandoned, a subscription
> mandate breaks, an invoice goes overdue. Most systems log it and stop.
> I built Recovery Copilot: an agent that detects the risk, figures out
> why, picks the right intervention, executes it for real, and proves
> the money it recovered — and what it cost to recover it."

## 0:20–0:50 — What it is

> "It's a Python agent behind a React dashboard — no Streamlit, this is a
> real app talking to a real API. A trained recoverability model scores
> every at-risk transaction, a root-cause detector catches infrastructure
> outages before blaming the customer, a policy engine picks one of six
> bounded actions under strict compliance stopping rules — and, the part
> most buildathon projects don't get to, it's connected to a real, live
> Razorpay account, executing real recovery actions against it."

## 0:50–1:30 — Dashboard tab

> "This is the Dashboard, on a batch of transactions." [Point at the hero
> line] "This period it recovered ₹X out of ₹Y at risk." [Point at the
> KPI row] "Recovered, recovery rate — and 'Spent recovering it': every
> action has a real modeled cost, SMS to a human agent, so this is net
> proof, not just gross recovered hiding an expensive way of getting
> there." [Point at Heads up] "It just caught a netbanking outage on its
> own — 37x normal — and paused retries instead of spamming customers
> during a bank-side problem, not a customer one."

## 1:30–2:10 — Transactions + Try a transaction

> "Every decision is explainable —" [open a transaction] "confidence, in
> plain language, exactly what it did, why, and what it cost — 'Show
> more' gets the full reasoning, 'technical details' gets the raw model
> and Razorpay call underneath." [Switch to Try a transaction] "This
> isn't canned — change the amount live" [drag it past ₹75,000] "and it
> flips straight to a specialist. Or take a new customer at a low
> score" [set customer type to New] "— a returning customer here would
> get left alone, but a merchant already paid to acquire this one, so
> the agent still sends a cheap nudge instead of writing them off. That's
> the kind of judgment call a real risk officer makes, not just a
> threshold."

## 2:10–4:00 — Live tab (the centerpiece)

> "Here's what makes this real, not a demo. This is a live, connected
> Razorpay account — Test Mode, so no real money moves, but every other
> part of this is genuine."
> [Open Live tab, show the embedded checkout] "I'll make a real payment
> and fail it on purpose." [Pick a customer type, pay with a real
> Razorpay test failure card]
> "The moment that fails, Razorpay's own servers call my webhook directly
> — no polling, no human — and the same model and policy engine that
> scored the batch scores this, in real time, right here on the checkout
> page the customer is still looking at." [Point at the decision box, the
> Pay now button] "It doesn't stop at a label — it creates a real,
> payable Razorpay Payment Link and emails it, immediately, because this
> is the customer responding to their own failed payment, not me reaching
> out to them unprompted — that distinction matters for the quiet-hours
> rule below it: outside business hours it still creates this link
> instantly, it just holds back the unprompted email until morning."
> [Scroll to the Live entries list] "Cost to recover, right next to
> confidence. And if a customer fails, gets this link, and fails again —"
> [point at a retry note if one's showing] "— that shows up as one
> purchase attempted twice, not two separate ones inflating what's
> actually at risk. And once a link gets paid, this tracks the real
> recovered amount against Razorpay's own API, live."

## 4:00–4:30 — Why this is more than a script

> "Three things make this a real system, not a demo of one: the score
> comes from an actual trained model, explainable per transaction. The
> root-cause detector separates a bank outage from a customer problem
> before anything else decides, checked first, ahead of every other rule.
> And the stopping rules — do-not-contact, attempt caps that escalate to
> a human for a VIP instead of silently giving up, an economical-amount
> floor — are checked before any customer-facing action, every time, with
> a full audit trail."

## 4:30–5:00 — Close

> "Recovery Copilot: detect, diagnose, decide, execute, prove — connected
> to a real payment gateway, executing real recovery actions, accounting
> for what they cost, not just describing what it would do. That's AI
> Revenue Recovery, actually recovering revenue."

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
- [ ] On the Try a transaction tab, know the two scenarios cold before
      recording: amount > ₹75,000 (value-triage escalation), and a New
      customer at a low score (sunk-cost nudge instead of a stop)
- [ ] Do one practice run of the Live tab flow before recording for real
      — payment → webhook → decision → execution can take a few seconds;
      if quiet hours happen to be active locally, say so on camera rather
      than let a held-back email look like a bug
- [ ] Screen + voice recording, ~5 minutes, upload (YouTube unlisted or a
      link-shared Drive file both work) and paste the link into the
      submission form
