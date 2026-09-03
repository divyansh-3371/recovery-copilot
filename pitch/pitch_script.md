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
> engine picks one of five bounded actions under strict stopping rules, and
> every single decision is logged to a full audit trail. Then a simulator
> proves the ₹ impact against a naive baseline on the same batch."

## 1:10–3:00 — Live demo (dashboard walkthrough)

The dashboard is five tabs — Try it live, Overview, Multi-day workflow,
Investigate, Merchant view — each answering a different question a real
viewer would ask.

0. **Try it live tab, first — prove it's not a canned demo.** Change the
   amount field from something mid-size down to ₹60 on camera:
   *"This isn't pre-computed — watch the decision itself change."* Point at
   it flipping from a nudge to "left alone, not worth pursuing" and the
   reasoning updating to cite the ₹150 recovery-cost floor, live, with a
   visible recompute timestamp. *"Same classifier, same policy engine, same
   Razorpay-call mapping running on whatever I type — not a fixed report."*
1. **Overview tab.** Point at the **consolidated systemic-issue card** first:
   *"The agent just caught a netbanking outage on its own — 37x the normal
   bank-timeout rate — and paused customer-facing retries for it instead of
   spamming people during an outage that isn't their fault."*
2. **KPI cards:** *"₹X at risk this batch, the agent recovered ₹Y gross —
   and after accounting for the actual cost of each intervention, ₹Z net —
   that's N% more than a naive single-retry baseline on the identical
   transactions, and it avoided M compliance violations the baseline would
   have committed."*
3. **Grouped bar chart:** *"Here's recovered revenue broken out by category —
   payment failures, checkout abandonment, subscription failures, overdue
   invoices — baseline vs Recovery Copilot, side by side."*
4. **Action chart — click a bar:** *"This is what the agent actually did —
   not just 'flagged as risky,' a concrete action. And it's not static —"*
   click any bar *"— clicking one shows a real example transaction that got
   that decision."*
5. **Merchant view tab:** *"And this is what the actual merchant using this
   would see — not the technical detail, just: how much did I get back,
   what's still in progress, what are my top failure reasons right now.
   Different audience, different view, same underlying agent."*
6. **Investigate tab — drill into one transaction:** pick one with a `SEND_MESSAGE` action.
   *"Here's the recoverability score and exactly why — the top factors that
   pushed it up or down. Here's the agent's reasoning for the action it
   chose. Here's the actual message it generated. And here's the full audit
   trail — every action, timestamped, with its reasoning, permanently
   logged."*
   Then pick one with `RETRY_PAYMENT` on a subscription failure:
   *"This isn't one blind retry — it's an explicit mandate retry sequence:
   immediate re-presentment, then a delayed retry, then a fallback to a
   manual re-authorization link if both silently fail."*
   Then find one with a promise-to-pay note (filter the table, or just
   re-roll the seed):
   *"And when a customer promises to pay by a date instead of paying
   immediately, the tracker doesn't just accept that at face value — it
   checks whether the promise was kept, and a broken one gets auto-escalated
   to a human agent instead of quietly disappearing."*
   Expand the "Razorpay API call this would trigger" box:
   *"And this isn't operating in the abstract — here's the actual Razorpay
   API call this decision would make in production."*

7. **Multi-day workflow tab:** *"Everything so far was one pass. This
   runs the same batch through the agent across several simulated days,
   with state actually persisting between them — so the retry sequencer
   genuinely advances step by step, and a promise-to-pay deadline
   genuinely arrives and gets checked, instead of every run starting from
   attempt zero. And it recovers even more than the single pass did,
   because a real workflow gets multiple scheduled chances."*
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
