# Deploy on Streamlit Community Cloud (easiest — no server, no SSH, free)

This hosts the dashboard straight from GitHub. No AWS, no Docker, no security groups, no SSH. You get a
public `https://…streamlit.app` URL you open on your phone. ~5 minutes.

> Read-only advisor/monitor; it never trades. The repo is **public**, so it's eligible.

## Prerequisite
Merge this branch to **main** (the deploy tracks a branch). The repo already has what Streamlit Cloud
needs: a `requirements.txt` (installs the package + UI) and the app **self-downloads** the price data on
first run.

## Steps
1. Go to **https://share.streamlit.io** and **sign in with GitHub** (authorize it to read your repos).
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `aarsh-adhvaryu/Q_Alpha`
   - **Branch:** `main`
   - **Main file path:** `scripts/dashboard_app.py`
4. Click **Advanced settings**:
   - **Python version:** `3.12`
   - **Secrets:** paste this (TOML), filling in your values — leave `APP_PASSWORD` set so the public
     URL is protected:
     ```toml
     KITE_API_KEY = "your_key"
     KITE_API_SECRET = "your_secret"
     APP_PASSWORD = "a-strong-passphrase"
     ```
     *(You can add/change these later under the app's **⋮ → Settings → Secrets**.)*
5. Click **Deploy**. First build takes a few minutes (it installs deps, then the app downloads market
   data once — you'll see a "downloading market data" spinner). When it's up, you get your URL.

## On your phone
Open the `…streamlit.app` URL → enter `APP_PASSWORD` → you're in. The **Paper book** view works with no
Kite login.

## Live Zerodha view
1. In the Kite developer console, set the app **Redirect URL** to your `https://…streamlit.app/` URL.
2. On the dashboard, switch the sidebar to **Live Zerodha** → tap **Login to Zerodha** → log in. Live
   holdings + prices appear; the page auto-refreshes (~30 s) for near-realtime.

## Good to know
- **Always fresh:** every push to `main` redeploys automatically — so the weekday paper-run cron's daily
  commit refreshes the app's paper book with no action from you.
- **Sleeps when idle:** the free tier puts the app to sleep after inactivity and wakes it on your next
  visit (a few-seconds cold start). Fine for a personal monitor.
- **Not for Stage-2 true ticks:** continuous WebSocket streaming needs an always-on server (a small
  paid host like Render/Railway, or the AWS path) — deferred. The auto-refresh here is the near-realtime
  stand-in.
- **Secrets are safe:** they live in Streamlit Cloud's secret store (bridged into the app's env), never
  in the repo.
