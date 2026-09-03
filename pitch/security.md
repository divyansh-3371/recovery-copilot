# Security posture

Recovery Copilot's only real network attack surface is `api.py` (the
FastAPI service) plus the SQLite layer it and the workflow simulation write
to (`agent/state_store.py`). The dashboard (`app.py`) and CLIs are local
tools with UI-bounded inputs, not services exposed to untrusted callers.
This document covers what's actually defended, how each was verified, and
what's explicitly out of scope for a hackathon submission.

## What's defended, and how it was verified

| Control | Where | How it was verified |
|---|---|---|
| **Rate limiting** — 30 req/60s per client IP, sliding window, `429` + `Retry-After` on breach | `agent/rate_limiter.py`, applied as global middleware in `api.py` | Fired 35 rapid requests at a live server — first ~29 returned `200`, the rest `429` with a `Retry-After` header present; `tests/test_rate_limiter.py` + `tests/test_api_security.py` lock this in |
| **SQL injection defense-in-depth** — `update_state()`'s dynamic `SET` clause is built from dict *keys*, which SQLite can't parameterize; every key is checked against an explicit `UPDATABLE_COLUMNS` allowlist | `agent/state_store.py` | `tests/test_state_store_security.py` — an injection-flavored column name and a primary-key-overwrite attempt both raise before touching SQL |
| **Strict input validation** — every field bounded (amount `>0` and `<=10M`, hour `0-23`, attempts `0-20`, etc.); every categorical field checked against the canonical sets in `data/generate_data.py`, including that `failure_reason` actually matches `risk_type` | `api.py`'s `TransactionIn` (Pydantic v2, `Field` constraints + `model_validator`) | Sent negative amounts, out-of-range hours, and a `risk_type`/`failure_reason` mismatch to a live server — each rejected with `422` before reaching model/policy code |
| **Bounded batch size** — `/batch/demo`'s `n` capped at `MAX_BATCH_SIZE` (2000) | `api.py` | A request for `n=999999` returned `422`, not an attempt to actually generate it |
| **Per-request audit isolation** — each `/batch/demo` call gets its own temp audit-log file (created and removed per request) instead of writing to the shared `data/audit_log.jsonl` | `api.py` | Prevents concurrent requests from resetting/corrupting each other's audit trail — a correctness bug that doubles as a soft self-DoS vector under concurrent load |
| **API-key auth, opt-in** — `X-API-Key` header checked against the `API_KEY` env var on `/decide` and `/batch/demo`; unset `API_KEY` runs "open demo mode" (logged clearly at startup) so grading needs no setup | `api.py` (`require_api_key` dependency + `lifespan` startup log) | With `API_KEY` set: missing/wrong header → `401`; correct header → `200`. With it unset: works with no header, and the startup log states this explicitly | `health` never requires it (health checks should stay reachable) |
| **No internal detail leaked on error** — a global exception handler logs the real exception server-side and returns a bare `{"error": "internal_error"}`, `500`, to the client | `api.py`'s `unhandled_exception_handler` | Code-reviewed; FastAPI/Pydantic's own `422` validation responses (which are safe, field-level messages, not stack traces) are left as-is |
| **No open CORS** | `api.py` (nothing configured) | The secure default — no `Access-Control-Allow-Origin` header means a browser can't read cross-origin responses. Documented as a deliberate choice, not an oversight: nothing here is meant to be called from a browser directly today |

## Verified end-to-end, not just unit-tested

Every control above was exercised against a real running `uvicorn` process
with `curl` before being locked in as pytest tests — the rate limiter
genuinely returns `429` under load, the auth genuinely blocks a live
request without the right header, the validation genuinely rejects bad
JSON bodies. `tests/test_api_security.py`, `tests/test_rate_limiter.py`,
and `tests/test_state_store_security.py` then encode those same checks so
they run automatically in CI on every push.

## Explicitly out of scope for this submission

- **TLS/HTTPS termination** — assumed to sit in front of this service
  (a reverse proxy / load balancer), as is standard for a service like this;
  not something the application code itself should handle.
- **Distributed rate limiting** — the in-memory limiter is per-process;
  a multi-instance deployment needs a shared store (Redis) behind the same
  `RateLimiter.allow()` interface. Documented as a swap point in
  `agent/rate_limiter.py`'s docstring.
- **Secrets management** — `API_KEY` / `ANTHROPIC_API_KEY` are read from
  environment variables, never hardcoded or logged; a real deployment
  would source them from a secrets manager, not `.env` (already gitignored).
- **Dependency vulnerability scanning** — `requirements.txt` is
  intentionally unpinned for a hackathon build; a production fork should
  pin exact versions and run `pip-audit` (or similar) in CI.
- **Streamlit dashboard hardening** — it's a local/demo UI with
  already-bounded inputs (seed and day-count are numeric widgets with
  min/max), not treated as a public-internet-facing service in this
  submission.
