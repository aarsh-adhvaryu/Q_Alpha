# AWS deploy — beginner, no-Docker, click-by-click

For a phone-accessible URL on AWS with **no Docker** and no prior AWS experience. You run the dashboard
directly on a small Ubuntu server (EC2). ~20 minutes. Read-only advisor/monitor; it never trades.

> **Do this first:** merge **PR #17** so `main` has the finished dashboard, then the server clones a
> single up-to-date `main`. (Otherwise you'd clone an older dashboard.)

---

## Phase 1 — Launch the server (AWS Console)
1. In the AWS Console search bar, type **EC2** → open it.
2. Click **Launch instance**.
3. **Name:** `qalpha-dashboard`.
4. **Application and OS Image:** choose **Ubuntu** (Ubuntu Server 24.04 LTS — it says *Free tier
   eligible*).
5. **Instance type:** `t3.micro` (or `t2.micro`) — *Free tier eligible*.
6. **Key pair:** click **Create new key pair** → name it `qalpha-key` → **Create** (a `.pem` file
   downloads; keep it, though we'll use browser login below).
7. **Network settings** → **Edit** → under *Inbound security group rules*:
   - Rule 1 (already there): **SSH**, port **22**, Source **My IP**.
   - Click **Add security group rule** → Type **Custom TCP**, **Port range 8501**, Source **My IP**.
     *(My IP = only your current network can reach the dashboard. The app also has a password.)*
8. Click **Launch instance** → then **View all instances**. Wait until **Instance state = Running**.

## Phase 2 — Open a terminal on the server (no .pem needed)
1. Select your instance → click **Connect** (top right).
2. Choose the **EC2 Instance Connect** tab → **Connect**. A black terminal opens in your browser.

## Phase 3 — Install + start the app (paste into that terminal)
Paste this whole block and press Enter:
```bash
sudo apt-get update -y && sudo apt-get install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
git clone https://github.com/aarsh-adhvaryu/Q_Alpha.git && cd Q_Alpha
uv sync --extra dashboard
uv run python scripts/build_nifty_universe.py
uv run python scripts/paper.py refresh
uv run python scripts/build_nifty100_watchlist.py --prices
```
That last block downloads the price data (a couple of minutes). Then start it:
```bash
uv run --extra dashboard streamlit run scripts/dashboard_app.py --server.address 0.0.0.0 --server.port 8501
```

## Phase 4 — Open it on your phone
1. On the instance page, copy the **Public IPv4 address** (e.g. `13.234.x.x`).
2. On your phone browser go to: **`http://<that-ip>:8501`**
3. You'll see the **Paper book** view immediately — no login needed. 🎉 That's your win.

## Phase 5 — Keep it running 24/7 (so closing the browser doesn't stop it)
The foreground run above stops when you close the terminal. To keep it alive, run it as a service:
```bash
sudo tee /etc/systemd/system/qalpha.service >/dev/null <<EOF
[Unit]
Description=Q-Alpha dashboard
After=network.target
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/Q_Alpha
EnvironmentFile=-/home/ubuntu/Q_Alpha/.env
ExecStart=/home/ubuntu/.local/bin/uv run --extra dashboard streamlit run scripts/dashboard_app.py --server.address 0.0.0.0 --server.port 8501
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now qalpha
```
Now it auto-starts and restarts forever (Ctrl-C / closing the terminal won't stop it).

## Phase 6 — LIVE Zerodha view + password (when ready)
```bash
cd /home/ubuntu/Q_Alpha && cp .env.example .env && nano .env
```
Fill in `KITE_API_KEY`, `KITE_API_SECRET`, `APP_PASSWORD`, save (Ctrl-O, Enter, Ctrl-X), then
`sudo systemctl restart qalpha`. In the Kite developer console set the app **Redirect URL** to
`http://<your-ip>:8501/`. On the dashboard switch to **Live Zerodha** → tap **Login to Zerodha**.

---

### If a price download is killed (t3.micro is 1 GB RAM)
Add a 2 GB swap file once, then re-run the bootstrap:
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

### Updating later
```bash
cd /home/ubuntu/Q_Alpha && git pull && uv sync --extra dashboard && sudo systemctl restart qalpha
```

### Security reminders
- Security group ports **22** and **8501** restricted to **My IP** (not `0.0.0.0/0`).
- Set a strong `APP_PASSWORD` before exposing the live view.
- `.env` holds secrets and is never committed.
- For public-Wi-Fi safety, add HTTPS later (a domain + Caddy — see `DEPLOY.md`).
