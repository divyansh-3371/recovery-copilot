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
