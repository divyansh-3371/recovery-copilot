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
