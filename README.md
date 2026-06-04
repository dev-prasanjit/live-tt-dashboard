# 📊 Tradetron Performance Dashboard

A real-time, self-healing analytics and reporting dashboard for [Tradetron](https://tradetron.tech) deployed strategies. It programmatically logs into your Tradetron session using browser automation, intercepts real-time prices via WebSocket frames directly in a background thread, scrapes live market index tickers, serves an interactive web dashboard, and runs a Telegram bot for scheduled and on-demand reporting.

---

## ✨ Features

- **Dynamic History Logs & 30-Day Quota** — Saves intraday mark-to-market snapshots dynamically as daily JSON files under a dedicated `history/` directory (`mtm_YYYY-MM-DD.json`). The server automatically enforces a 30-day quota, sorting and deleting the oldest log files once the threshold is exceeded to maintain a clean sliding window on disk.
- **Historical Date Select Dropdown** — A dynamic selector dropdown in the chart header lets you load any of the past 30 days' recorded charts instantly. The selection dynamically queries the backend database for the historical file and redraws the graph.
- **Individual Strategy Overlays** — Individual strategy P&L performance lines are overlaid directly onto the overall portfolio line chart. Each strategy is color-coded with vibrant, high-contrast colors matching the theme.
- **Interactive Legend Toggling** — Click on any strategy name in the chart legend to toggle that specific strategy's line visibility on or off, allowing you to isolate and compare performance without leaving the main view.
- **Theme-Aware Canvas Downloader** — A dedicated download button exports the current chart view (overall line plus any currently active/toggled strategy lines) as a solid background PNG image, matching the active theme's background (`#1e293b` for dark, `#ffffff` for light).
- **Automated Data Extraction & Session Healing** — Programmatically logs into your Tradetron account via browser automation using [get_tradetron_data.py](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/get_tradetron_data.py), solving the cryptographic mathematical ALTCHA captcha automatically. If session cookies expire, the unified backend launcher automatically triggers session healing to regenerate cookies without user intervention.
- **Unified Multi-Threaded Daemon Server** — Powered by [dashboard_server.py](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/dashboard_server.py), which runs a local HTTP Server, a Playwright Chromium scraper thread, a Google Finance indices ticker thread, and a Telegram command listener concurrently.
- **Dynamic NSE Holiday Calendar** — Automatically fetches the latest official National Stock Exchange (NSE) trading holidays list from a community-maintained repository on startup, caches it locally (`nse_holidays_cache.json`), and exposes it to the frontend via `/api/market-holidays`. On holidays, all scrapers are paused, the watch badge displays `Closed`, and the intraday MTM chart renders a flat zero line.
- **WebSocket Price Interception** — Listens to Tradetron's Centrifuge WebSocket connection frames on the backend. When a live Last Trade Price (LTP) frame is received, the price is cached in-memory and exposed via the HTTP endpoint `/api/live-prices` to feed real-time calculations.
- **daisyUI & Tailwind CSS Redesign** — Modern responsive UI built with **daisyUI v5** and **Tailwind CSS v4** featuring a premium glassmorphic layout, floating animated color blobs, custom scrollbars, and high-contrast styling.
- **Dual Theme Switcher (Light / Dark)** — A clean toggle switch in the header that swaps between the `light` and `dark` themes. Toggling themes updates the page colors instantly, saves your choice in `localStorage`, and redraws the Chart.js canvas with high-contrast text and grid colors. FOUC (flash of unstyled content) is prevented by an early-execution inline theme script.
- **Zero-Crossing MTM Chart** — An interactive intraday P&L line graph (using Chart.js) that renders instantly with custom gradients. The chart line and area fill dynamically change colors at the `0` baseline: **emerald green** when today's P&L is positive, and **rose red** when below zero.
- **Color-Coded Status Badges & Broker Grouping** — Strategy statuses (e.g. `Active`, `Live-Entered`, `Paused`, `Exited`, `Error`) are color-coded in the table using matching daisyUI status classes. Broker cells inside the table are dynamically assigned distinctive background colors from a curated palette to visually group strategies by broker.
- **Indices & Digital Clock Tracker** — Embedded tracker scraping live Google Finance tickers for Nifty 50, Sensex, Bank Nifty, and India VIX. Updates every 10 seconds during market hours. Includes a digital watch displaying the current IST time including seconds and current market state (`Live` vs `Closed`).
- **Telegram Command Console** — Sends automated P&L reports every 30 minutes from 9:30 AM to 3:30 PM IST (with a 10-minute grace period to ensure the 15:30 close report is successfully sent). Also listens for manual `/report` or `/status` commands, which support broker-specific filtering (e.g. `/report FT` for Flattrade) using shortcodes configured in your environment.

---

## 📁 Project Structure

All dashboard files are located under the `tradetron_dashboard/` directory:

- [dashboard_server.py](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/dashboard_server.py) — The primary backend application orchestrating the HTTP server, Playwright scrapers, indices thread, and Telegram listener.
- [get_tradetron_data.py](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/get_tradetron_data.py) — Automated browser-based login utility script that logs in and generates authentication cookies.
- [requirements.txt](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/requirements.txt) — Python package dependencies (Playwright, PyTZ, etc.).
- [com.tradetron.dashboard.plist](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/com.tradetron.dashboard.plist) — macOS LaunchAgent plist for automated boot execution.
- [tradetron-dashboard.service](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/tradetron-dashboard.service) — Linux systemd service configuration for boot execution.
- [market_open_baselines.json](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/market_open_baselines.json) — Records cumulative strategy performance at market open to calculate today's intraday P&L.
- [history/](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/history) — Directory containing daily historical MTM JSON files named `mtm_YYYY-MM-DD.json`.
- [tradetron_cookies.json](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/tradetron_cookies.json) — Saved session cookies extracted from browser automation.
- [dashboard.log](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/dashboard.log) — Standard output log for background processes.
- **frontend/** — Directory containing client-side assets served by the HTTP server:
  - [index.html](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/frontend/index.html) — HTML5 layout structured with Tailwind CSS and daisyUI components.
  - [style.css](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/frontend/style.css) — Custom stylesheet providing float animations, index update flashes, and overrides.
  - [app.js](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/frontend/app.js) — Main UI logic managing live price polling, data calculation, status classes, broker styling, and Chart.js theme adjustments.
  - [data.json](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/frontend/data.json) — Strategies baseline configuration and positions fetched from the Tradetron API.

---

## ⚙️ Architecture & Data Flow

```
                      ┌─────────────────────────────────────────────────────────────┐
                      │                     dashboard_server.py                     │
                      │                                                             │
                      │  ┌──────────────┐    ┌───────────────────────────────────┐  │
                      │  │  HTTP Server  │    │      Playwright Scraper Thread    │  │
                      │  │  (Port 8080)  │    │      (Background Thread Loop)     │  │
                      │  │               │    │                                   │  │
                      │  │  Serves:      │    │  1. Pages through Tradetron API   │  │
                      │  │  - index.html │    │  2. Solves ALTCHA captcha on fail │  │
                      │  │  - JSON APIs  │◀───│  3. Intercepts WS LTP price frames│  │
                      │  │  - data.json  │    │  4. Records MTM snaps to history/ │  │
                      │  └──────────────┘    └───────────────────────────────────┘  │
                      │                                │                            │
                      │  ┌─────────────────────────────┼─────────────────────────┐  │
                      │  │  Telegram Bot Listener      ▼                         │  │
                      │  │  - Scheduled Reports (9:30 AM - 3:30 PM IST)          │  │
                      │  │  - Commands: /report, /status [broker_code]           │  │
                      │  └───────────────────────────────────────────────────────┘  │
                      │  ┌───────────────────────────────────────────────────────┐  │
                      │  │  Indices Loop Scraper                                 │  │
                      │  │  - Google Finance scraping (Nifty, Sensex, Bank, Vix) │  │
                      │  └───────────────────────────────────────────────────────┘  │
                      └─────────────────────────────────────────────────────────────┘
```

1. **Automation & Extraction Loop**:
   - The backend runs a headless Playwright Chromium session, loading cookies from `tradetron_cookies.json`.
   - It iterates through pages on `https://tradetron.tech/api/deployed-strategies` to extract strategy configurations and positions, saving them in `frontend/data.json`.
   - It intercepts Tradetron's Centrifuge WebSocket connection using Chromium's network-level hooks. Real-time price updates (Last Trade Prices) are captured from WebSocket frames, stored in-memory in `latest_prices`, and served through the `/api/live-prices` endpoint.
2. **Session Self-Healing**:
   - If an API fetch returns an `Unauthenticated` status, the background loop pauses and launches [get_tradetron_data.py](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/get_tradetron_data.py).
   - This utility loads Chromium, enters credentials from `.env`, solves the mathematical ALTCHA proof-of-work captcha, submits the form, waits for dashboard redirection, and writes fresh cookies back to disk. The main server thread reloads the new cookies and resumes.
3. **Indices and Watch Threads**:
   - The server maintains a separate thread that queries Google Finance HTML endpoints for Nifty 50, Sensex, Bank Nifty, and India VIX. Prices are scraped and exposed via `/api/live-indices`.
   - During market hours, updates run every 10 seconds. Off-market, they scale back to every 60 seconds.
4. **Calculations and Rendering**:
    - At 9:10 AM (5 minutes before market open), the scraper records/updates baseline metrics (`all_pnl_at_market_open`) in `market_open_baselines.json`.
   - The frontend `app.js` polls `/api/live-prices` every 10 seconds (only during market hours).
   - It applies these prices to open positions to calculate real-time strategy values:
     $$\text{Position P\&L} = (\text{LTP} \times \text{Quantity}) - \text{Entry Value}$$
     $$\text{Strategy Run P\&L} = \text{Open Positions P\&L} + \text{Closed Positions P\&L}$$
     $$\text{Strategy Total P\&L} = \text{Baseline Total P\&L} + (\text{Strategy Run P\&L} - \text{Initial Run P\&L})$$
     $$\text{Today's Est. P\&L} = \text{Strategy Total P\&L} - \text{Baseline Total P\&L at Market Open}$$
   - These computed metrics populate the statistics cards and Strategy Table.
5. **Dynamic MTM Snapshots**:
   - The client posts the current cumulative Today's Est. P&L value and individual strategy P&Ls to the server's `/api/record-mtm` endpoint every minute.
   - The server records the snapshot in `history/mtm_YYYY-MM-DD.json` labeled with the current IST timestamp.
   - At 15:30 IST, if the market closes, snapshots freeze at the 15:30 value. They are preserved until 2:00 AM IST of the following day to prevent the line graph from disappearing when you open the page after market hours.
   - For historical days (non-today), the client queries `/api/mtm-history?date=YYYY-MM-DD` which returns the static recorded history file from disk.

---

## 🚀 Quick Start

### 1. Installation

Install Python (3.8+) dependencies:
```bash
pip install -r requirements.txt
playwright install --with-deps chromium
```

### 2. Configure Environment

Create a `.env` file in the `tradetron_dashboard/` directory matching the following template (see [.env.example](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/.env.example)):
```env
# Tradetron Login Credentials
TRADETRON_EMAIL=your_email@example.com
TRADETRON_PASSWORD=your_password_here

# Telegram Bot configurations (Optional)
TELEGRAM_BOT_TOKEN=1234567890:ABC-DEF1234ghIkl-zyx987wvu
TELEGRAM_CHAT_ID=987654321

# Broker Shortcodes for Filtered Reports (Optional)
# Format: SHORTCODE:Broker Name in Tradetron (comma separated)
BROKER_SHORTCODES=FT:Flattrade,JR:Jainam Retail (XTS),ZR:Zerodha
```

### 3. Generate Session Cookies

Initialize the automation sequence to generate your first cookie payload:
```bash
python3 get_tradetron_data.py
```
This launches a headless Chromium script, fills credentials, solves ALTCHA, logs in, and saves cookies to `tradetron_cookies.json`.

### 4. Run the Dashboard

Start the server process in standard or unbuffered output mode:
```bash
python3 -u dashboard_server.py
```
Open your browser and navigate to **[http://localhost:8080](http://localhost:8080)**.

To execute the daemon as a persistent background process:
```bash
nohup python3 -u dashboard_server.py > dashboard.log 2>&1 &
```

---

## 📱 Telegram Command Interface

If configured, you can query your dashboard directly from your Telegram client.

- `/report` or `/status` — Sends a formatted markdown report of all active strategies, their current statuses, capitals, P&Ls, and return percentages.
- `/report <shortcode>` — Sends a filtered report showing only strategies linked to the specified broker (e.g. `/report FT` maps to Flattrade).

---

## 🔄 Daemon & Service Configurations

### macOS (LaunchAgent)

To run the dashboard server automatically on boot:
1. Edit [com.tradetron.dashboard.plist](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard/com.tradetron.dashboard.plist) to replace paths with your actual project workspace and virtual environment paths.
2. Copy the plist file to LaunchAgents:
   ```bash
   cp com.tradetron.dashboard.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.tradetron.dashboard.plist
   ```

### Linux (systemd)

For cloud VPS deployments:
1. Edit [tradetron-dashboard.service](file:///Users/prasanjitdatta/Desktop/antigravity/tradetron-dashboard/tradetron-dashboard.service) to adjust execution paths.
2. Register and start the system service:
   ```bash
   sudo cp tradetron-dashboard.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable tradetron-dashboard
   sudo systemctl start tradetron-dashboard
   ```

---

## 🛠️ Troubleshooting

| Issue | Potential Cause | Resolution |
|---|---|---|
| **Empty tables or stale data** | Scraper thread blocked or crashed. | Check the status in `dashboard.log` and verify the process is alive: `ps aux \| grep python3`. |
| **Port 8080 address in use** | A previous instance of the server is still running. | Kill the socket process: `kill -9 $(lsof -t -i:8080)` and restart. |
| **Unauthenticated warnings in logs** | Cookies have expired or `.env` credentials are invalid. | The backend will automatically trigger cookie healing. If it repeatedly fails, run `python3 get_tradetron_data.py` manually to diagnose. |
| **ALTCHA solver timeouts** | Chromium dependencies are missing or web components changed. | Re-run `playwright install chromium` to verify browser binaries. |
| **Telegram commands not replying** | Chat ID is mismatching or token is incorrect. | Ensure the sender's Chat ID matches `TELEGRAM_CHAT_ID` and the bot is initialized by sending a `/start` message first. |

---

## 📜 License

Private project. All rights reserved. Do not redistribute.
