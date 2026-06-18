# Deploying on Lightning AI (recommended — you're already here)

You're developing inside a Lightning AI Studio, so the repo, data, and price panels are already
present. Hosting the dashboard is a ~2-minute job — no AWS, no Docker, no security groups.

> Read-only advisor/monitor; it never trades. Real-money GO is still gated by the forward paper run.

## 1. Install the dashboard deps (once)
```bash
uv sync --extra dashboard
```

## 2. Secrets
```bash
cp .env.example .env && nano .env      # or set these as Studio environment variables
```
```
KITE_API_KEY=...
KITE_API_SECRET=...
APP_PASSWORD=<a strong passphrase>     # REQUIRED — the URL is public; this gates your holdings
```

## 3. Get a public URL
**Easiest — the Streamlit plugin:** add the **Streamlit** plugin to the Studio, point it at
`scripts/dashboard_app.py`, and click the **public-link** icon. You get a phone-accessible URL in
under a minute.

**Manual alternative — the Ports plugin:**
```bash
uv run --extra dashboard streamlit run scripts/dashboard_app.py \
  --server.port 8501 --server.address 0.0.0.0 --server.headless true
```
then expose **8501** via the **Ports** plugin and use its public URL.

## 4. Always-on (auto-start)
Enable **auto-start** on the app: Lightning keeps it available 24/7 but **only bills while it's being
used**, sleeping it when idle (a few-minutes cold-start on the next visit). Ideal for a personal
monitor.

> ⚠️ Auto-start's idle-sleep is fine for **Stage 1** (near-realtime: each visit re-fetches `ltp()`).
> It is **not** compatible with **Stage 2** true tick-streaming (a continuously-running `KiteTicker`
> WebSocket) — that needs the Studio kept *genuinely* always-running (continuous credits). Choose
> auto-start for cheap near-realtime, or a persistent Studio for true ticks.

## 5. Point your Kite app's redirect URL at the dashboard
In the Kite developer console set the app **Redirect URL** to your Lightning public URL (e.g.
`https://<your-app>.litng.ai/`). That's what makes the **one-tap phone login** work: after you log in,
Kite redirects back with the `request_token`, which the app exchanges automatically.

## 6. Daily use (phone)
- Open the URL → enter `APP_PASSWORD`.
- Each morning the Kite token has expired → tap **"Login to Zerodha"**, log in (~10 s) → live data.
- The **Paper-run** panel shows whether the weekday pipeline marked the book. **Note:** the cron
  commits to GitHub, so the Studio must `git pull` to show fresh marks — hit **"Reload data"**, or run
  a periodic pull (e.g. a Studio cron: `*/30 * * * *  cd ~/Q_Alpha && git pull -q`).

## Why not AWS?
You can (see `DEPLOY.md` for the EC2/Lightsail + Docker path — portable to any VPS). But on Lightning
everything's already provisioned and the public URL is one click, so for you this is simpler. The only
edge AWS has is a **free** 12-month always-on tier (relevant only if you want Stage-2 true-ticks running
24/7 at zero cost).
