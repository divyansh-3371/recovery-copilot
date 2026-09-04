# 5-minute pitch script — Recovery Copilot

Timing is a guide, not a script to read verbatim — say it in your own words.

## 0:00–0:40 — The problem (hook)

> "Revenue loss at a payments company almost never happens in one clean
> step. A payment degrades, a checkout gets abandoned, a subscription
> mandate fails, an invoice goes overdue. Most systems treat each of these
> as a dead end — log it, maybe fire one generic retry, move on. I built
> Recovery Copilot: an agent that closes the loop — detects the revenue at
> risk, figures out *why* it's at risk, picks the cheapest intervention that
> will actually work, executes it, and proves with real numbers that it
> recovered more money than doing nothing smarter would have."

## 0:40–1:10 — What it is, in one breath

> "It's a Python agent pipeline: a trained recoverability model scores every
> at-risk transaction, a root-cause detector watches for infrastructure
> outages so we don't blame the customer for the bank's problem, a policy
> engine picks one of six bounded actions under strict stopping rules, and
> every single decision is logged to a full audit trail. Then a simulator
> proves the ₹ impact against a naive baseline on the same batch."

## 1:10–3:00 — Live demo (dashboard walkthrough)

The dashboard is four tabs — Dashboard, Transactions, Recovery timeline,
Try a transaction — designed to read like a real product a merchant would
actually use, not a technical review screen. Every technical/audit detail
is still there, just tucked into a collapsed "Technical details" section
on the tabs that have one, so the primary view stays clean.

1. **Dashboard tab.** Lead with the hero number: *"This period, Recovery
   Copilot recovered ₹X for you, out of ₹Y at risk."* Point at the
   **Heads up card**: *"The agent just caught a netbanking outage on its
   own — 37x the normal rate — and paused customer-facing retries for it
   instead of spamming people during an outage that isn't their fault."*
   Then the KPI row and the two charts: *"Recovered by category, before
   Recovery Copilot vs after — and what's actually happening operationally."*
   Click a bar on the "What's happening" chart: *"Not static — clicking
   shows a real example transaction that got that decision."*
2. **Transactions tab.** Filter or scroll to any row, then look one up:
   *"Here's Recovery Copilot's confidence and exactly why — in plain
   language, not a model dump. Here's what we did and why. Here's the
   actual message that went to the customer."* Expand **Technical details**:
   *"And if you want the raw model output, the exact Razorpay API call
   this would trigger, and the full timestamped audit trail — it's all
   right here, not hidden."* Find one with a promise-to-pay note:
   *"When a customer promises to pay instead of paying immediately, the
   tracker checks whether that promise was kept — a broken one gets
   auto-escalated, not quietly dropped."*
3. **Recovery timeline tab:** *"The Dashboard is one snapshot. This shows
   what happens over several simulated days as Recovery Copilot follows
   up — and it recovers even more than the single snapshot, because
   follow-up gives every case multiple chances, not just one."*
4. **Try a transaction tab, to close the demo — prove it's not a canned
   report.** Change the amount field from something mid-size down to ₹60
   on camera: *"Watch the decision itself change, live — not pre-computed."*
   Point at it flipping from a reminder to "left alone, not worth pursuing."
   Then push it above ₹75,000 on any reason: *"— and now it goes straight
   to a specialist, regardless of what the usual reason-based routing
   would have picked. Same engine as everywhere else on this page, running
   on whatever you type."*
8. **If you have a `voice_hinglish` transaction:** click play. *"For
   returning customers who've already missed one attempt, the agent
   switches to a Hinglish voice nudge — synthesized fully offline, no
   internet dependency."*

## 3:00–4:00 — Why this is more than a script with if/else

> "Three things make this a real system, not a demo toy: the recoverability
> score comes from an actual trained model, not a hardcoded rule, and it's
> fully explainable per transaction. The root-cause detector catches
> systemic infrastructure problems before the policy engine ever decides to
> retry — that's the difference between a system that understands payments
> and one that just spams customers. And the stopping rules aren't a
> suggestion — do-not-contact, attempt caps, and an economical-amount floor
> are checked before anything else, every time."

## 4:00–4:40 — What broke, and what I learned fixing it

> "The root-cause detector didn't fire at all on the first random batch —
> splitting by payment method fragmented the volume too much for a natural
> spike to clear the threshold. I fixed it the way real monitoring demos
> do: inject one deliberate, labeled incident so the detector has something
> reliable to catch — and it ended up catching a second, unplanned pattern
> in the random data too, which told me the detector logic itself was
> sound." *(See `pitch/build_challenges.md` for the full list — five real
> issues, each with its root cause and fix.)*

## 4:40–5:00 — Close

> "Recovery Copilot: detect, diagnose, decide, execute, prove — with an
> audit trail a compliance reviewer could actually read. That's AI Revenue
> Recovery done the way Razorpay's own bar asks for it."

---

## Recording checklist

- [ ] `streamlit run app.py` running locally before you hit record
- [ ] Pick a batch seed in advance that shows a systemic issue banner (default seed 42 does)
- [ ] Have one `SEND_MESSAGE` transaction and one `voice_hinglish` transaction ID noted for the drill-down
- [ ] Screen + voice recording, 5 minutes, upload and paste the link into the submission form
