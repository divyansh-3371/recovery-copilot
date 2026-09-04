# Connecting a real Razorpay account (Test Mode)

Everything on the code side is already built and tested (`agent/razorpay_live.py`,
`api.py`'s `/checkout/*` and `/webhooks/razorpay`, `checkout.html`,
`tests/test_razorpay_live.py`, `tests/test_razorpay_webhook_api.py`). What's
below is the part only you can do — creating the account and generating
credentials — plus the handful of commands to wire them in. None of it
touches code; it's ~10 minutes.

**Do this on your own machine, never in chat** — don't paste your Key
Secret or Webhook Secret to anyone, including here. They're your account's
credentials.

## 1. Create a Razorpay account

1. Go to https://dashboard.razorpay.com/signup and sign up.
2. You land in **Test Mode** by default (top-left toggle in the dashboard)
   — stay there. Test Mode moves no real money and needs no business
   KYC/activation to start.

## 2. Generate Test Mode API keys

1. Dashboard → **Settings → API Keys** (or **Account & Settings → API Keys**).
2. Click **Generate Test Key**. You'll see:
   - **Key ID** (`rzp_test_...`) — public, safe to expose to a browser.
   - **Key Secret** — shown once. Copy it now; you can't view it again
     (you'd have to regenerate).

## 3. Set the environment variables (never hardcode these)

In `D:\razor`, create a file named `.env` (already gitignored — it will
never be committed):

```
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_key_secret_here
```

Then load it before starting the API, for example in PowerShell:

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^([^=]+)=(.*)$') { Set-Item "Env:$($Matches[1])" $Matches[2] }
}
uvicorn api:app --reload
```

(Or just set them directly in the shell you launch `uvicorn` from —
`$env:RAZORPAY_KEY_ID = "..."` etc. Either way, restart `uvicorn` after
setting them.)

Confirm it picked them up:

```powershell
curl http://localhost:8000/razorpay/status
# {"configured":true}
```

Open http://localhost:8000/checkout in a browser — the "TEST MODE" badge
page should let you click **Pay with Razorpay** and open a real Razorpay
checkout modal.

## 4. Make a test payment

Use one of Razorpay's own [documented test
cards](https://razorpay.com/docs/payments/payments/test-card-upi-details/)
— these are real, Razorpay-recognized test instruments, not fake numbers
that happen to pass Luhn checks:

- A normal test card completes the payment; `/checkout/verify` on the
  backend confirms the signature and the page shows "Payment verified by
  the backend."
- Razorpay also documents specific test cards/flows that **simulate a
  failure** (e.g. an "always declines" test card) — use one of those to
  trigger a real `payment.failed` event, which is what step 6 needs to see
  end-to-end.

## 5. Expose your local server publicly (webhooks need a real URL)

Razorpay's servers call your webhook over the internet — `localhost` isn't
reachable from there. Use a tunnel. [ngrok](https://ngrok.com/download) is
the simplest:

```powershell
ngrok http 8000
```

Copy the `https://...ngrok-free.app` URL it prints. Keep this window open
while you're testing — the tunnel dies when it closes, and you'll need to
re-register the webhook URL if it changes on restart (the free tier
rotates URLs each time).

## 6. Register the webhook in the Razorpay dashboard

1. Dashboard → **Settings → Webhooks → Add New Webhook**.
2. **Webhook URL**: `https://<your-ngrok-subdomain>.ngrok-free.app/webhooks/razorpay`
3. **Secret**: type a new secret of your own choosing (any strong random
   string — this is a value you invent, not one Razorpay gives you).
4. **Active events**: check at least `payment.failed` (you can also enable
   `payment.captured` — the receiver already handles/ignores events it
   doesn't act on).
5. Save.

Now set that same secret as an environment variable, exactly as in step 3:

```
RAZORPAY_WEBHOOK_SECRET=the_secret_you_typed_in_step_6
```

Restart `uvicorn` after adding it.

## 7. Watch it work, live

With the tunnel running, `uvicorn` running with all three env vars set,
and the webhook registered:

1. Open http://localhost:8000/checkout (or your ngrok URL + `/checkout`).
2. Pay with a test card that Razorpay documents as a **failure** case.
3. Within seconds, Razorpay calls your `/webhooks/razorpay` — no dashboard
   click, no polling, nothing manual — and Recovery Copilot's real
   classifier + policy engine scores and decides on it immediately.
4. Check `data/live_audit_log.jsonl` (a new file, separate from the
   synthetic-batch `data/audit_log.jsonl`) — one JSON line with the real
   `transaction_id` (Razorpay's actual `pay_...` ID), the recoverability
   score, the decision, and the full reasoning trail.

That file is the proof: a real payment failure, from a real (Test Mode)
Razorpay account, processed end-to-end by the actual agent — not a
simulation.

## What this does and doesn't prove

- **Real**: order creation, checkout, backend signature verification (a
  forged/tampered browser callback is rejected — verified in
  `tests/test_razorpay_live.py`), and the webhook receiver's HMAC check
  and real-time hand-off into the same classifier/policy pipeline used
  everywhere else in this project.
- **Not yet built**: the webhook receiver decides but doesn't (yet) act —
  e.g. `RETRY_PAYMENT` doesn't automatically fire a real retry via the
  Orders API, and `SEND_MESSAGE` doesn't automatically send a real SMS/email.
  `agent/razorpay_client.py`'s call-shape mapping shows exactly what those
  calls would look like; wiring them to actually fire is the natural next
  step once retry/notification credentials (SMS gateway, etc.) are also in
  place.
- **Test Mode only**: going live (real money) requires Razorpay's business
  KYC/activation, which is out of scope here — Test Mode is what the
  buildathon needs and is what this guide sets up.
