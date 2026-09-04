# Build challenges & technical obstacles

Real issues hit while building, and how each was resolved. This is the source
for the submission form's "Build Challenges & Technical Obstacles" field.

## 1. Root-cause detector didn't trigger on purely random data

**Problem:** the first version of `agent/root_cause.py` grouped failures by
`(payment_method, failure_reason)` to spot spikes. On a randomly generated
batch, splitting by payment method fragmented volume enough that no group
cleared the "recent count" threshold — the feature worked in theory but
never fired in practice, which is useless for a live demo.

**Fix:** injected a deliberate, clearly-labeled synthetic outage into
`data/generate_data.py` (`N_INJECTED_OUTAGE` netbanking `bank_timeout`
events concentrated in the last day) — the same technique real monitoring
system demos use to guarantee a reproducible incident instead of hoping one
appears by chance. The detector still runs the same statistical check
against the *whole* batch, so it also happened to catch a second, unplanned
pattern (`mandate_bank_error`) that emerged from the random data — good
evidence it's a real detector, not one hardcoded to the injected case.

## 2. Windows console mangled the em-dash character

**Problem:** decision reasoning strings used a Unicode em-dash (—); printed
to the Windows terminal (cp1252 codepage) it rendered as `�`, and would have
looked broken in the pitch video / judge's console output.

**Fix:** switched user-facing, console-printed strings to plain ASCII
hyphens. (Text stored in the audit log file and shown in the browser
dashboard was never affected — only direct terminal `print()` output.)

## 3. Streamlit API deprecation

**Problem:** `st.plotly_chart(..., use_container_width=True)` and
`st.dataframe(..., use_container_width=True)` are deprecated in the
installed Streamlit version (removal after 2025-12-31), printing warnings on
every run.

**Fix:** migrated all call sites to the new `width="stretch"` parameter.

## 4. Headless-browser screenshot showed loading skeletons, not the real UI

**Problem:** verifying the dashboard with a headless Playwright screenshot
initially captured empty gray placeholder boxes where the KPI metrics and
Plotly charts should be — `page.goto(..., wait_until="networkidle")` doesn't
account for Streamlit's persistent websocket connection, which keeps
delivering the actual rendered content *after* the network looks idle.

**Fix:** waited for specific rendered elements instead of network state —
`[data-testid="stMetricValue"]` and `.js-plotly-plot` — before taking the
screenshot.

## 5. Scrolling the dashboard for a full-page screenshot did nothing

**Problem:** `page.mouse.wheel()` and a `full_page=True` screenshot both
failed to reach content below the fold — Streamlit's main content area
scrolls inside its own internal `overflow-y` container, not the document
body, so window-level scroll APIs are no-ops.

**Fix:** ran a small JS snippet that finds the actual scrollable container
(`scrollHeight - clientHeight > threshold`) and scrolls that element
directly, then took viewport screenshots at each scroll position.

## 6. Two named track directions were missing entirely

**Problem:** re-reading Razorpay's exact track text against the built
codebase turned up two of the seven named "example directions" that weren't
properly covered — the mandate retry sequence existed only as inline,
ad-hoc delay logic buried in `policy.py` (not an explicit, inspectable
component), and a promise-to-pay tracker didn't exist at all.

**Fix:** added `agent/retry_sequencer.py` (an explicit multi-step retry
table for payments and mandates) and `agent/promise_tracker.py` (classifies
promise-to-pay outcomes and auto-escalates broken ones), and wired both into
`policy.py` / `simulator.py` / `pipeline.py`. The lesson: check the spec's
named list item-by-item against the actual code, not against what the
build was *intended* to cover.

## 7. Installing fastapi/uvicorn silently downgraded Streamlit's dependency

**Problem:** `pip install fastapi uvicorn` resolved to a `fastapi` version
pinned to `starlette<0.42`, downgrading the already-installed `starlette`
from 1.6.0 to 0.41.3 — which is below the `>=0.46` Streamlit itself
requires. Streamlit still happened to import afterward, but it was one
`pip install` away from silently breaking the whole dashboard.

**Fix:** `pip install --upgrade fastapi starlette` to pull a recent
`fastapi` release with a wider `starlette` range, resolving both
constraints together. Lesson: after adding any new dependency, re-verify
the *existing* stack still imports — don't assume a successful `pip
install` means nothing else moved.

## 8. A collapsed Streamlit expander broke the screenshot verification script

**Problem:** after adding the "Day-by-day detail" expander (collapsed by
default) above the transaction table, the Playwright verification script's
`wait_for_selector('[data-testid="stDataFrame"]')` started timing out —
it matched the *first* dataframe in DOM order, which was the one hidden
inside the collapsed expander, and Playwright's default visibility wait
never resolves for a hidden element even when later, visible instances of
the same selector exist on the page.

**Fix:** switched the wait condition to a specific, always-visible text
anchor (`text=Transaction queue`) instead of a selector that could match a
hidden element first. General lesson for this project: prefer waiting on
content known to be visible over a generic selector that might match
inside a collapsed/hidden container.

## 9. A test wrote a SQL-injection-style attack that failed for the wrong reason

**Problem:** a test tried to prove `update_state()` refuses to let an
attacker-controlled `**fields` dict overwrite `transaction_id`. It failed
with `TypeError: got multiple values for argument 'transaction_id'` instead
of the expected `ValueError` from the column allowlist.

**Fix:** the test's assumption was wrong, not the code -- `transaction_id`
is a named parameter of `update_state()` itself, so it can never reach
`**fields` in the first place; Python's own call-binding rejects the
collision before the allowlist check even runs, which is arguably a
stronger guarantee. Updated the test to assert the real (safe) behavior
instead of the assumed one, and documented why in its docstring.

## 10. A code-level re-review found real gaps behind claims that sounded complete

**Problem:** the README described the failure-reason handling, retry timing,
guardrails, audit trail, and proof layer as done. A line-by-line re-review
of the actual code against five specific criteria found this was only
partly true:
- The failure-reason -> intervention mapping was hardcoded if/elif in
  `policy.py`, duplicated as a *separate* hardcoded tuple in `simulator.py`
  (`RETRY_FRIENDLY_REASONS`) -- two sources of the same truth, one edit away
  from silently drifting apart.
- A refactor two sessions earlier (extracting `retry_sequencer.py`) had
  quietly **dropped** failure-reason-specific retry timing that used to
  exist inline (`0.5h for bank_timeout/network_drop, else 6h`) -- replaced
  with a single attempt-number-only sequence, a real regression nobody had
  caught because there was no test pinning the old behavior down.
- "Risk-engine block" wasn't in the failure taxonomy at all.
- Idempotency (cancelling remaining actions when a customer pays through a
  channel the agent never touched) was never implemented -- only ever
  claimed as an emergent property of "skip if resolved," which doesn't
  cover payment happening *outside* the agent's own actions.
- The audit trail never logged `failure_reason` or the outcome of a
  decision, only the decision itself.
- The proof layer reported gross ₹ recovered but never the cost of
  getting there.

**Fix:** `agent/decision_table.py` consolidates the failure-reason judgment
calls into one place; `agent/retry_sequencer.py` now takes an optional
`failure_reason` to restore the lost timing distinction; `risk_block` was
added to the taxonomy and routed to mandatory human review; `agent/workflow.py`
gained an explicit pre-decision independent-payment check; `pipeline.py`/
`workflow.py` log `failure_reason` and a follow-up outcome entry per
decision; `agent/cost_model.py` + updated `summarize()` report net recovered
after cost. 19 new tests pin all of this down so it can't silently regress
again. Lesson: a claim of "done" needs to be checked against the actual
diff, not the intent behind the commit message.

## 11. `@app.on_event("startup")` is deprecated in the installed FastAPI

**Problem:** running the test suite with `-W error::DeprecationWarning`
turned up a `DeprecationWarning` on `@app.on_event("startup")` -- the
installed FastAPI version has moved to `lifespan` context managers.

**Fix:** replaced it with an `@asynccontextmanager` `lifespan` function
passed to `FastAPI(..., lifespan=lifespan)`, and re-verified the startup
warning (API_KEY unset -> "open demo mode" log) still fires against a real
running server, not just that the app still imports.

## 12. A textbook-correct chart form still failed real-user comprehension

**Problem:** the baseline-vs-agent comparison used a dumbbell chart (two
dots per category connected by a line) -- the standard, correct form for
"before vs after per item" per data-viz guidance. A person looking at the
actual dashboard read it as "just an image and sliders" and had no idea
what it showed. Same critique landed on the three separate systemic-issue
banners (repetitive, no hierarchy) and the sidebar's judge-facing checklist
("The Bar this demo targets" / "Example directions covered") -- content
useful to a reviewer of the code, not to anyone looking at the running app.

**Fix:** replaced the dumbbell with a grouped bar chart (the same "compare
two series per category" job, but a form nobody misreads); consolidated
the three banners into one card with compact bullet lines; moved the
judge-facing checklist into a collapsed sidebar expander instead of
always-on screen real estate; split the single long-scroll page into four
tabs (Overview / Multi-day workflow / Investigate / Merchant view) so each
answers one question instead of dumping everything at once; added a
genuinely new interactive element (click a bar in "what the agent decided"
to see a real example transaction, verified working via a real Playwright
click, not just code review); and added the merchant-view tab as its own
audience-appropriate page rather than reusing the technical one. Lesson:
a chart form being the textbook-correct choice doesn't guarantee a real
viewer reads it correctly -- watch someone actually look at it before
calling a visualization done.

## 13. The dashboard recomputed live but never proved it was doing so

**Problem:** the seed control and day-slider already triggered real
recomputation on every change, but nothing on screen made that visible --
from a viewer's side, static pre-baked charts and genuinely-live-but-
identical-looking charts render identically until you already know the
mechanism. The complaint was fair: it read as "a static website," even
though the underlying computation was real.

**Fix:** added a "Try it live" tab where the viewer directly controls the
model/policy inputs (amount, failure reason, payment method, attempts...)
via ordinary widgets, and the score/decision/reasoning/cost/Razorpay-call
recompute on every change with no submit button -- Streamlit's own rerun
model makes this free once the inputs are wired to the same `classifier`/
`policy`/`cost_model` calls the rest of the app uses. Verified end-to-end,
not just written: dropped the amount from ₹5,000 to ₹60 in a live browser
and confirmed the decision actually flipped from "sent a nudge" to "left
alone, not worth pursuing" with the ₹150-floor reasoning updating to match,
plus a visible recompute timestamp in the sidebar. Also added a "Randomize
batch" button so the seed control's effect is a one-click, obvious gesture
instead of something you have to already understand to notice.

## 14. A live crash: two processes writing the same audit log raced

**Problem:** the live dashboard crashed with `json.decoder.JSONDecodeError:
Expecting value: line 1 column 1 (char 0)` inside `AuditTrail.load_all()`,
reported with a real screenshot while the app was running. Root cause,
confirmed by scanning the actual file: `data/audit_log.jsonl` is the
default, shared path used by *both* the live Streamlit app and every CLI
run (`run_batch.py`, `simulate_workflow.py`) -- and during this session
both were run against the same file around the same time. `reset()`
truncates the file (`open(path, "w")`); if that lands while another
process is mid-read or mid-append, a single JSON entry can get split
across two garbled lines. A direct scan turned up exactly that: 14
corrupted lines out of 5,472, the textbook signature of an unguarded
concurrent write, not a one-off fluke.

**Fix:** `load_all()` now wraps each line's `json.loads()` in its own
try/except and skips (with a logged warning) any line that fails to parse,
instead of letting one bad line take down the entire audit trail read.
Verified against the actual corrupted file on disk, not a synthetic
repro: 5,458 of 5,472 lines loaded cleanly, the 14 bad ones skipped, no
crash. Five new tests, including one built from a hand-crafted torn-line
file reproducing the exact failure mode. Lesson: a shared file path
written from more than one process needs defensive reads by default --
"this worked in every test I ran" isn't the same claim as "this is safe
under concurrent access," and this bug only ever showed up because a real
person was clicking the real app while other processes were also touching
its data.

## 15. Repeat-contact messages read identical to the first one

**Problem:** self-identified, not hit as a crash -- `messenger.py` generated
the same tone regardless of how many times a customer had already been
contacted. A customer nudged three times would see three identical
messages, which reads as either a bug or as the agent not actually
tracking that it had already tried.

**Fix:** message tone now escalates across three tiers keyed off
`previous_attempts` (capped at 2, since the policy engine's max-attempts
stopping rule means a message is never sent past that): tier 0 is warm and
low-pressure, tier 1 is a polite follow-up, tier 2 is an explicit "final
reminder" that's more direct without being pushy. Applied to both the
template fallback (English and Hinglish, default and invoice-specific
copy -- 12 template strings total) and the LLM prompt (which now states
the attempt number and target tone explicitly). Verified live: attempts
0/1/2 on the identical transaction produce visibly different text ("Hi
Test, your payment didn't go through..." -> "just a quick follow-up..." ->
"this is a final reminder..."), not just different in theory. 5 new tests.

## 16. A "snooze and re-score" idea turned out to be theater -- the real gap was elsewhere

**Problem:** asked whether the 5-action, 14-path decision space was missing
anything. Two real gaps: no distinct action for severely-overdue B2B
collections (conflated with ordinary human escalation), and a `STOP`'d
transaction's score never gets revisited even though the agent gave up on
it.

**The second one didn't hold up under scrutiny.** Every feature feeding a
never-acted-on transaction's score (amount, segment, attempts, reason) is
static -- re-running the identical score computation tomorrow produces the
identical number. There is no real information a "re-score" would ever
pick up; faking a reason for the number to drift would be adding noise for
the appearance of sophistication, not a real fix. Caught this by tracing
through what would actually be different on re-evaluation, not by building
it first and finding out.

**The real gap, found in the same investigation:** a `STOP`'d transaction
was skipped by the workflow loop entirely -- including the independent-
payment check -- so a customer who paid on their own through another
channel *after* the agent gave up on them was never noticed, silently
undercounting real recovered revenue. That's a genuine, fixable gap, and a
different one from what was originally proposed.

**Fix:** `agent/policy.py` gained `ESCALATE_COLLECTIONS` -- a severely
overdue (45+ day), high-value invoice now routes to formal collections/
legal (higher cost, distinct from a recovery agent's outreach) instead of
being folded into `ESCALATE_HUMAN`, checked ahead of the generic value-
triage catch-all so the more specific routing wins. `agent/workflow.py`'s
loop now separates "should we still watch for organic payment" (yes,
always, until actually resolved) from "should the agent take a new
action" (no, once terminal) -- previously conflated into one guard clause.
Verified on the real batch: 30 of 625 transactions in a 5-day run were
stopped early *and* later resolved independently -- real revenue that was
being silently missed before this fix, not a hypothetical. 7 new tests.
Lesson: when a proposed fix doesn't survive tracing through what data
would actually change, that's a signal to look for the real gap
underneath it rather than build the theater anyway.

## 17. The dashboard was designed for the reviewer, not the person who'd actually use it

**Problem:** asked to make the dashboard look professional for an *end
user*, not a reviewer. A pass through the actual copy turned up genuinely
reviewer-only language leaking into what should have been product UI --
the sidebar's "About" expander literally said *"Targets Razorpay's own bar
for this track,"* section headers read like a data-science notebook
("Recoverability score 0.60", raw feature names like
`cat__customer_segment_vip`), and the polished merchant-facing page built
earlier was buried as a fifth tab instead of being the default view.

**Fix:** consolidated five tabs into four (Dashboard, Transactions,
Recovery timeline, Try a transaction), with the merchant-facing content
promoted to the default landing tab instead of a side tab. Rewrote every
piece of reviewer-facing copy in the sidebar and headers. Added a
`_friendly_feature()` translator so "why" explanations read as "customer
type: vip -- a strong factor that improves the chances of recovery"
instead of raw sklearn feature names, and a `display_reasoning()` cleanup
pass that turns "Recoverability score 0.60" into "Confidence (60%)" and
strips quoted internal identifiers, applied to every reasoning string
shown in the primary view. All genuinely technical detail (raw feature
contributions, the exact Razorpay API call, the full timestamped audit
trail) still exists in full -- moved into a collapsed "Technical details"
expander per transaction, not deleted, so a judge who wants the depth
still gets it without it being the default experience for everyone else.
Verified every tab live after the rewrite, including that the cleanup
regex doesn't mangle real reasoning text (tested against all the actual
strings the policy engine produces, not synthetic examples).
