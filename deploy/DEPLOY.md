# Deploying the Q-Alpha dashboard (phone-accessible URL on AWS)

> **Already on Lightning AI? Use [`DEPLOY_LIGHTNING.md`](DEPLOY_LIGHTNING.md) instead — it's a one-click
> public URL, no AWS/Docker needed.** This AWS/Docker path is the portable alternative (any VPS), and
> its only edge is a *free* 12-month always-on tier.

Goal: a private URL you open on your phone that shows your real holdings, live prices, the tax-smart
advisor, the deploy-in-weakness engine, and the paper-run status — so the **only** manual step is
placing the order in Kite. This is a **read-only advisor/monitor**; it never trades.

> Honest scope: the real-money GO is still gated by the forward paper run. This deploys the *advisor*,
> which is appropriate. And per Kite's design, the daily session needs a **one-tap login** (below) —
> there is no compliant fully-unattended token.

## What you need
- An **AWS account** (Free Tier / student credits work).
- Your **Kite Connect app** (https://developers.kite.trade): note the **API key** + **API secret**.
- ~15 minutes.

## 1. Launch an instance (always-on)
Either works; **Lightsail** is the simplest for one user.
- **EC2 (Free Tier):** Ubuntu 24.04, **t3.micro** (750 hrs/month free for 12 months). 
- **Lightsail:** Ubuntu, the **$5/mo** plan (1 GB RAM).

In the instance's **security group / firewall**, open **TCP 8501** — and restrict the source to
**your own IP** (or a VPN), not `0.0.0.0/0`. Your portfolio should not be world-reachable even behind
the password.

## 2. Install Docker + the repo
```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER && newgrp docker
git clone https://github.com/aarsh-adhvaryu/Q_Alpha.git && cd Q_Alpha
```

## 3. Secrets
```bash
cp .env.example .env && nano .env
```
Fill in:
```
KITE_API_KEY=...           # from your Kite app
KITE_API_SECRET=...        # from your Kite app
APP_PASSWORD=<a strong passphrase>   # gates the dashboard
```
`.env` is gitignored — your secrets stay on the box. **Never** put the API secret in the repo.

## 4. Point your Kite app's redirect URL at the dashboard
In the Kite developer console, set the app **Redirect URL** to your dashboard's login page:
```
http://<your-ec2-ip>:8501/        (or https://<your-domain>/ if you add TLS — step 7)
```
This is what makes the **one-tap phone login** work: after you log in, Kite redirects back to the
dashboard with the `request_token`, which the app exchanges for the day's access token automatically.

## 5. Run it
```bash
docker compose -f deploy/docker-compose.yml up -d --build
```
First boot downloads the price panels (a couple of minutes; cached in a volume afterwards). Then open
**`http://<your-ec2-ip>:8501`** on your phone → enter `APP_PASSWORD` → you're in.

## 6. Daily use
- Each morning the Kite token has expired → the dashboard shows a **"Login to Zerodha"** button. Tap
  it, log in (10 sec), and you're back to live data for the day.
- The **paper-run status** panel shows whether the weekday pipeline marked the book — so you *see* it's
  alive, not trust it. (The cron lives in `.github/workflows/paper.yml`.)
- Live prices auto-refresh while the page is open (near-realtime). For true tick-streaming see below.

## 7. (Optional) HTTPS + a domain
Front it with Caddy for automatic HTTPS (needs a domain pointed at the instance):
```bash
sudo apt-get install -y caddy
sudo caddy reverse-proxy --from your-domain.com --to localhost:8501
```
Then update the Kite redirect URL to `https://your-domain.com/`.

## Updating
```bash
git pull && docker compose -f deploy/docker-compose.yml up -d --build
```

## Stage 2 — true tick streaming (not in this image yet)
This deploy gives **near-realtime** prices via auto-refresh (re-fetches `ltp()` every ~30s). **True
ticking** (live, sub-second) uses Kite's **WebSocket** (`KiteTicker`): a background thread on the
always-on box subscribes to your holdings and pushes ticks to the page. It's deliberately staged —
it can only be built and verified against the live socket on *this* box, with a fresh token — so it's
the next increment once the box is up. The advisor/monitor is fully usable on auto-refresh meanwhile.

## Security checklist
- [ ] Security group restricts **8501** to your IP (not the world).
- [ ] `APP_PASSWORD` set and strong.
- [ ] `.env` never committed (it's gitignored).
- [ ] API **secret** only in `.env` on the box; the daily access token is minted via login, not stored
      in the repo.
- [ ] Prefer HTTPS (step 7) before using over public Wi-Fi.
