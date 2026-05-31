import json
import os
import time
import datetime
import pytz
import threading
import urllib.request
import urllib.parse
import re
from http.server import SimpleHTTPRequestHandler, HTTPServer

# Force Playwright browser path inside the project directory when running in cloud environments
if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") is None and (os.path.exists("/app") or os.environ.get("RAILWAY_ENVIRONMENT")):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/app/.cache/ms-playwright"

from playwright.sync_api import sync_playwright

# Load .env for Telegram credentials
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

COOKIES_FILE = 'tradetron_cookies.json'
OUTPUT_FILE = 'frontend/data.json'
BASELINES_FILE = 'market_open_baselines.json'
MTM_HISTORY_FILE = 'mtm_history.json'
HOLIDAYS_CACHE_FILE = 'nse_holidays_cache.json'
nse_holiday_dates = set()

def load_nse_holidays():
    global nse_holiday_dates
    url = "https://raw.githubusercontent.com/sonufsd/nse-holiday-calendar/master/src/data/nse-holidays.json"
    headers = {
        'User-Agent': 'Mozilla/5.0'
    }
    
    # 1. Try to download from github
    try:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Downloading latest NSE holidays from GitHub...")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            raw_data = response.read().decode('utf-8')
            # Validate JSON
            parsed = json.loads(raw_data)
            # Save to local cache
            with open(HOLIDAYS_CACHE_FILE, 'w') as f:
                f.write(raw_data)
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Successfully cached NSE holidays list locally.")
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Warning: Failed to download NSE holidays: {e}")
        
    # 2. Try to read from local cache file
    parsed_data = None
    if os.path.exists(HOLIDAYS_CACHE_FILE):
        try:
            with open(HOLIDAYS_CACHE_FILE, 'r') as f:
                parsed_data = json.load(f)
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Loaded NSE holidays from local cache.")
        except Exception as e:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Error reading local NSE holidays cache: {e}")
            
    # 3. Fallback to hardcoded list if both failed
    if parsed_data is None:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Warning: Using hardcoded fallback NSE holidays for 2026.")
        parsed_data = {
            "2026": [
                {"date": "2026-01-26"}, {"date": "2026-03-03"}, {"date": "2026-03-26"},
                {"date": "2026-03-31"}, {"date": "2026-04-03"}, {"date": "2026-04-14"},
                {"date": "2026-05-01"}, {"date": "2026-05-28"}, {"date": "2026-06-26"},
                {"date": "2026-09-14"}, {"date": "2026-10-02"}, {"date": "2026-10-20"},
                {"date": "2026-11-10"}, {"date": "2026-11-24"}, {"date": "2026-12-25"}
            ]
        }
        
    # Extract all dates into set
    temp_set = set()
    try:
        for year, h_list in parsed_data.items():
            if isinstance(h_list, list):
                for item in h_list:
                    if isinstance(item, dict) and "date" in item:
                        temp_set.add(item["date"])
        nse_holiday_dates = temp_set
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Successfully loaded {len(nse_holiday_dates)} NSE holiday dates.")
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Error parsing NSE holidays data: {e}")

# Run once at startup
load_nse_holidays()

cached_ws_token = None
latest_prices = {}
latest_indices = {
    "NIFTY": {"price": 0.0, "change": 0.0, "pct": 0.0},
    "SENSEX": {"price": 0.0, "change": 0.0, "pct": 0.0},
    "BANK_NIFTY": {"price": 0.0, "change": 0.0, "pct": 0.0},
    "INDIA_VIX": {"price": 0.0, "change": 0.0, "pct": 0.0}
}

# Intraday MTM history: list of {"time": "HH:MM", "pnl": float}
# Persisted to disk so it survives server restarts. Resets at 2 AM IST.
mtm_history = []
mtm_history_date = None  # Track which trading day the history belongs to

HISTORY_DIR = 'history'
os.makedirs(HISTORY_DIR, exist_ok=True)

def get_today_ist_date():
    tz = pytz.timezone('Asia/Kolkata')
    return datetime.datetime.now(tz).strftime('%Y-%m-%d')

def load_mtm_history(date_str=None):
    """Load MTM history for a specific day from its dynamic file."""
    global mtm_history, mtm_history_date
    is_today = False
    if date_str is None:
        date_str = get_today_ist_date()
        is_today = True
    elif date_str == get_today_ist_date():
        is_today = True
        
    file_path = os.path.join(HISTORY_DIR, f"mtm_{date_str}.json")
    history_list = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict):
                history_list = data.get('history', [])
            else:
                history_list = data
            
            if is_today:
                mtm_history = history_list
                mtm_history_date = date_str
            print(f"Loaded {len(history_list)} MTM points for {date_str} from {file_path}")
        except Exception as e:
            print(f"Warning: Could not load MTM history for {date_str}: {e}")
    else:
        if is_today:
            mtm_history = []
            mtm_history_date = date_str
            
    return history_list

def enforce_history_quota():
    """Keep only the last 30 daily history files (delete oldest first)."""
    try:
        files = [f for f in os.listdir(HISTORY_DIR) if f.startswith("mtm_") and f.endswith(".json")]
        files.sort()
        if len(files) > 30:
            files_to_delete = files[:-30]
            for file_name in files_to_delete:
                old_file_path = os.path.join(HISTORY_DIR, file_name)
                os.remove(old_file_path)
                print(f"Deleted old MTM history file to maintain 30-day quota: {old_file_path}")
    except Exception as e:
        print(f"Warning: Failed to enforce history quota: {e}")

def save_mtm_history():
    """Persist current today's MTM history to disk and enforce 30-day quota."""
    global mtm_history, mtm_history_date
    if not mtm_history_date:
        mtm_history_date = get_today_ist_date()
        
    file_path = os.path.join(HISTORY_DIR, f"mtm_{mtm_history_date}.json")
    try:
        with open(file_path, 'w') as f:
            json.dump({'date': mtm_history_date, 'history': mtm_history}, f, indent=4)
        print(f"Saved MTM history to {file_path}")
        enforce_history_quota()
    except Exception as e:
        print(f"Warning: Could not save MTM history: {e}")

def migrate_legacy_history():
    """Migrate legacy mtm_history.json to history/mtm_YYYY-MM-DD.json on startup."""
    legacy_file = 'mtm_history.json'
    if os.path.exists(legacy_file):
        try:
            with open(legacy_file, 'r') as f:
                data = json.load(f)
            
            date_str = data.get('date', None)
            history_list = data.get('history', [])
            
            if date_str and history_list:
                dest_path = os.path.join(HISTORY_DIR, f"mtm_{date_str}.json")
                if not os.path.exists(dest_path):
                    with open(dest_path, 'w') as f:
                        json.dump(data, f, indent=4)
                    print(f"Migrated legacy history file to {dest_path}")
            
            os.rename(legacy_file, legacy_file + ".bak")
            print(f"Renamed legacy {legacy_file} to {legacy_file}.bak")
        except Exception as e:
            print(f"Warning: Failed to migrate legacy history file: {e}")

# Migrate and load on module init
migrate_legacy_history()
load_mtm_history()

# Event to communicate between the HTTP server thread and the Playwright fetch loop thread
trigger_fetch_event = threading.Event()

class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve the 'frontend' directory statically
        super().__init__(*args, directory="frontend", **kwargs)

    def do_GET(self):
        # Intercept the API endpoint for retrieving Centrifuge JWT token
        if self.path == '/api/ws-token':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            global cached_ws_token
            response = {"token": cached_ws_token}
            self.wfile.write(json.dumps(response).encode('utf-8'))
        elif self.path == '/api/live-prices':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            global latest_prices
            self.wfile.write(json.dumps(latest_prices).encode('utf-8'))
        elif self.path == '/api/live-indices':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            global latest_indices
            self.wfile.write(json.dumps(latest_indices).encode('utf-8'))
        elif self.path.startswith('/api/mtm-history'):
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            date_param = query_params.get('date', [None])[0]
            
            if date_param:
                history_list = load_mtm_history(date_param)
            else:
                global mtm_history
                history_list = mtm_history
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(history_list).encode('utf-8'))
        elif self.path == '/api/history-days':
            days = []
            try:
                files = [f for f in os.listdir(HISTORY_DIR) if f.startswith("mtm_") and f.endswith(".json")]
                for f in files:
                    date_part = f.replace("mtm_", "").replace(".json", "")
                    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_part):
                        days.append(date_part)
                days.sort(reverse=True)
            except Exception as e:
                print(f"Error loading history days list: {e}")
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(days).encode('utf-8'))
        elif self.path == '/api/market-holidays':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            global nse_holiday_dates
            self.wfile.write(json.dumps(list(nse_holiday_dates)).encode('utf-8'))
        else:
            super().do_GET()

    def do_POST(self):
        # Intercept the API endpoint from the UI refresh button
        if self.path == '/api/force_refresh':
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] UI Button clicked! Triggering forced live fetch...")
            trigger_fetch_event.set()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"refresh_triggered"}')
        elif self.path == '/api/record-mtm':
            # Frontend pushes current MTM value for server-side history tracking
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                pnl_value = float(data.get('pnl', 0))
                strategies_pnl = data.get('strategies', None)
                record_mtm_snapshot(pnl_value, strategies_pnl)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"recorded"}')
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_error(404)

def record_mtm_snapshot(pnl_value, strategies_pnl=None):
    """Record a timestamped MTM P&L snapshot containing overall and strategy P&Ls."""
    global mtm_history, mtm_history_date
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.datetime.now(tz)
    today_str = now.strftime('%Y-%m-%d')
    
    # Cap timestamp to 15:30 if current time is past 15:30 IST on the same trading day
    market_close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now > market_close_time:
        time_str = "15:30"
    else:
        time_str = now.strftime('%H:%M')
    
    # Only reset if:
    # 1. The stored date is from a previous day AND
    # 2. Current IST time is past 2:00 AM (so data is preserved overnight until 2 AM)
    if mtm_history_date and mtm_history_date != today_str and now.hour >= 2:
        mtm_history = []
        mtm_history_date = today_str
        print(f"[{now.strftime('%H:%M:%S')}] MTM history reset for new trading day: {today_str}")
    elif mtm_history_date is None:
        mtm_history_date = today_str
    
    snapshot = {
        'time': time_str,
        'pnl': round(pnl_value, 2)
    }
    if strategies_pnl:
        snapshot['strategies'] = {name: round(float(val), 2) for name, val in strategies_pnl.items() if val is not None}
        
    # Avoid duplicate entries for the same minute
    if mtm_history and mtm_history[-1]['time'] == time_str:
        mtm_history[-1] = snapshot
    else:
        mtm_history.append(snapshot)
    
    # Persist to disk after each recording
    save_mtm_history()
    
    print(f"[{now.strftime('%H:%M:%S')}] MTM snapshot recorded: {time_str} = ₹{pnl_value:,.2f} ({len(mtm_history)} points)")

def get_or_create_baselines(strategies):
    # Get today's date in IST
    tz = pytz.timezone('Asia/Kolkata')
    today_str = datetime.datetime.now(tz).strftime('%Y-%m-%d')
    
    baselines = {}
    if os.path.exists(BASELINES_FILE):
        try:
            with open(BASELINES_FILE, 'r') as f:
                baselines = json.load(f)
        except Exception as e:
            print(f"Error reading baselines: {e}")
            
    today_baselines = baselines.get(today_str, {})
    
    updated = False
    for s in strategies:
        strat_id = str(s["id"])
        if strat_id not in today_baselines:
            # First time seeing this strategy today. Save its current all_pnl as baseline.
            today_baselines[strat_id] = float(s.get("all_pnl", 0) or 0)
            updated = True
            
    if updated:
        baselines[today_str] = today_baselines
        try:
            with open(BASELINES_FILE, 'w') as f:
                json.dump(baselines, f, indent=4)
        except Exception as e:
            print(f"Error saving baselines: {e}")
            
    return today_baselines

def is_nse_holiday(date_obj):
    global nse_holiday_dates
    date_str = date_obj.strftime('%Y-%m-%d')
    return date_str in nse_holiday_dates

def is_market_open():
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.datetime.now(tz)
    if now.weekday() >= 5: return False
    if is_nse_holiday(now): return False
    market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now <= market_end

def is_within_notification_window():
    """Like is_market_open() but with a 5-minute grace period after market close.
    This ensures the 15:30 Telegram notification fires even if the 5-minute
    fetch cycle timer ends a few seconds (or minutes) after 15:30:00."""
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.datetime.now(tz)
    if now.weekday() >= 5: return False
    if is_nse_holiday(now): return False
    window_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    window_end = now.replace(hour=15, minute=40, second=0, microsecond=0)
    return window_start <= now <= window_end

def fetch_indices():
    global latest_indices
    url_nifty = "https://www.google.com/finance/quote/NIFTY_50:INDEXNSE"
    url_vix = "https://www.google.com/finance/quote/INDIA_VIX:INDEXNSE"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, deltas) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    # 1. Fetch Nifty, Sensex, Bank Nifty
    req_nifty = urllib.request.Request(url_nifty, headers=headers)
    try:
        with urllib.request.urlopen(req_nifty, timeout=5) as response:
            html = response.read().decode('utf-8')
            nifty_pat = r'\["NIFTY_50"\s*,\s*"INDEXNSE"\]\s*,\s*"NIFTY 50"\s*,\s*1\s*,\s*null\s*,\s*\[([\d.]+)\s*,\s*([\d.-]+)\s*,\s*([\d.-]+)'
            sensex_pat = r'\["SENSEX"\s*,\s*"INDEXBOM"\]\s*,\s*"BSE SENSEX"\s*,\s*1\s*,\s*null\s*,\s*\[([\d.]+)\s*,\s*([\d.-]+)\s*,\s*([\d.-]+)'
            bank_nifty_pat = r'\["NIFTY_BANK"\s*,\s*"INDEXNSE"\]\s*,\s*"Nifty Bank"\s*,\s*1\s*,\s*null\s*,\s*\[([\d.]+)\s*,\s*([\d.-]+)\s*,\s*([\d.-]+)'
            
            m_nifty = re.search(nifty_pat, html)
            m_sensex = re.search(sensex_pat, html)
            m_bank = re.search(bank_nifty_pat, html)
            
            if m_nifty:
                latest_indices["NIFTY"] = {
                    "price": float(m_nifty.group(1)),
                    "change": float(m_nifty.group(2)),
                    "pct": float(m_nifty.group(3))
                }
            if m_sensex:
                latest_indices["SENSEX"] = {
                    "price": float(m_sensex.group(1)),
                    "change": float(m_sensex.group(2)),
                    "pct": float(m_sensex.group(3))
                }
            if m_bank:
                latest_indices["BANK_NIFTY"] = {
                    "price": float(m_bank.group(1)),
                    "change": float(m_bank.group(2)),
                    "pct": float(m_bank.group(3))
                }
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Error scraping main indices: {e}")

    # 2. Fetch India VIX
    req_vix = urllib.request.Request(url_vix, headers=headers)
    try:
        with urllib.request.urlopen(req_vix, timeout=5) as response:
            html = response.read().decode('utf-8')
            vix_pat = r'\["INDIA_VIX"\s*,\s*"INDEXNSE"\]\s*,\s*"Nifty VIX"\s*,\s*1\s*,\s*null\s*,\s*\[([\d.]+)\s*,\s*([\d.-]+)\s*,\s*([\d.-]+)'
            m_vix = re.search(vix_pat, html)
            if m_vix:
                latest_indices["INDIA_VIX"] = {
                    "price": float(m_vix.group(1)),
                    "change": float(m_vix.group(2)),
                    "pct": float(m_vix.group(3))
                }
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Error scraping VIX: {e}")

def indices_loop():
    while True:
        try:
            if is_market_open():
                fetch_indices()
                time.sleep(5)
            else:
                if latest_indices["NIFTY"]["price"] == 0.0 or latest_indices["INDIA_VIX"]["price"] == 0.0:
                    fetch_indices()
                time.sleep(60)
        except Exception as e:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Error in indices_loop: {e}")
            time.sleep(10)

def format_capital_lakh(capital):
    lakhs = capital / 100000
    return f"{lakhs:g}L"

def get_broker_shortcodes():
    raw = os.environ.get("BROKER_SHORTCODES", "")
    mapping = {}
    if raw:
        for pair in raw.split(","):
            if ":" in pair:
                code, name = pair.split(":", 1)
                mapping[code.strip().upper()] = name.strip()
    return mapping

def get_broker_shortcode(broker_name):
    if not broker_name:
        return "N/A"
    shortcodes = get_broker_shortcodes()
    for code, name in shortcodes.items():
        if name.lower() in broker_name.lower() or broker_name.lower() in name.lower():
            return code
    # Clean and fallback
    cleaned = re.sub(r'[^a-zA-Z]', '', broker_name)
    return cleaned[:3].upper() if cleaned else "BRK"


def generate_telegram_report(strategies, broker_filter=None):
    if broker_filter:
        lines = [f"📊 *Tradetron Report — {broker_filter}* 📊\n"]
    else:
        lines = ["📊 *Tradetron Hourly Update* 📊\n"]
    
    total_pnl = 0
    
    for s in strategies:
        if s.get("deployment_type") != "LIVE AUTO":
            continue
        
        # Broker filter: match against strategy_broker.broker.name
        if broker_filter:
            broker_name = ""
            sb = s.get("strategy_broker")
            if sb and isinstance(sb, dict):
                broker_name = sb.get("broker", {}).get("name", "")
            if broker_filter.lower() not in broker_name.lower():
                continue
            
        template = s.get("template", {})
        name = template.get("name", "Unknown")
        status = s.get("status", "Unknown")
        
        base_cap = float(template.get("capital_required", 0) or 0)
        multiplier = float(s.get("minimum_multiple", 1) or 1)
        cap = base_cap * multiplier
        
        current_pnl = float(s.get("sum_of_pnl", 0) or 0)
        total_pnl += current_pnl
        
        circle = "🟢" if current_pnl >= 0 else "🔴"
        pnl_pct = (current_pnl / cap * 100) if cap > 0 else 0
        
        # 🟢 Strategy name - Status - ₹Current PNL (Capital in Lakh | PNL percentage based on capital)
        lines.append(f"{circle} *{name}* - {status} - ₹{current_pnl:,.2f} ({format_capital_lakh(cap)} | {pnl_pct:+.2f}%)")
        
    if len(lines) == 1:
        return None
        
    return "\n".join(lines)

def send_telegram_message(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def fetch_loop():
    while True:
        try:
            if not os.path.exists(COOKIES_FILE):
                email = os.environ.get("TRADETRON_EMAIL")
                password = os.environ.get("TRADETRON_PASSWORD")
                if not email or not password:
                    print("[fetch_loop] Error: Cookies file not found, and TRADETRON_EMAIL/TRADETRON_PASSWORD are not set in environment variables! Please configure them in Railway variables. Retrying in 10 seconds...")
                    time.sleep(10)
                    continue
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Cookies file '{COOKIES_FILE}' not found. Initializing session auto-recovery...")
                import subprocess
                subprocess.run(["python3", "get_tradetron_data.py"])
                if not os.path.exists(COOKIES_FILE):
                    print("Session auto-recovery failed to generate cookies. Retrying in 10 seconds...")
                    time.sleep(10)
                    continue

            with open(COOKIES_FILE, 'r') as f:
                cookies = json.load(f)

            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as e:
                    err_str = str(e)
                    if "Executable doesn't exist" in err_str or "playwright install" in err_str or "headless_shell" in err_str:
                        print("[Playwright] Browser executable not found. Running dynamic installation ('playwright install chromium')...")
                        import subprocess
                        subprocess.run(["python3", "-m", "playwright", "install", "chromium"])
                        browser = p.chromium.launch(headless=True)
                    else:
                        raise
                context = browser.new_context()
                context.add_cookies(cookies)
                page = context.new_page()
                
                # Intercept WebSocket frames to extract real-time price updates
                def on_websocket(ws):
                    def on_frame(payload):
                        try:
                            if isinstance(payload, str):
                                data = json.loads(payload)
                                if "push" in data:
                                    push = data["push"]
                                    channel = push.get("channel")
                                    pub_data = push.get("pub", {}).get("data", {})
                                    val = pub_data.get("value")
                                    if val is None:
                                        val = pub_data.get("msg", {}).get("LastTradePrice")
                                    if channel and val is not None:
                                        global latest_prices
                                        latest_prices[channel] = float(val)
                        except Exception as e:
                            pass
                    ws.on("framereceived", on_frame)
                page.on("websocket", on_websocket)

                print("Establishing Tradetron Session...")
                try:
                    page.goto("https://tradetron.tech/user/dashboard", timeout=45000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception as e:
                    print(f"Warning: UI took too long to load, but proceeding to API fetch anyway: {e}")
                print("Session active. Background loop started.")
                
                # Initial fetch on startup
                trigger_fetch_event.set()
                last_telegram_interval = None
                
                while True:
                    # Wait for 300 seconds in 1-second increments, yielding control to Playwright's event loop
                    triggered = False
                    for _ in range(300):
                        if trigger_fetch_event.is_set():
                            triggered = True
                            break
                        page.wait_for_timeout(1000)
                        
                    trigger_fetch_event.clear() # Reset flag immediately
                    
                    # If 300 seconds passed naturally (not triggered manually) AND we're outside
                    # the notification window, skip the fetch. We use a wider window than
                    # is_market_open() to ensure the 15:30 notification isn't missed when the
                    # 5-minute sleep ends a few seconds after 15:30:00.
                    if not triggered and not is_within_notification_window():
                        continue 

                    all_strategies = []
                    current_page = 1
                    last_page = None
                    
                    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Executing data extraction pipeline...")
                    
                    try:
                        # Refresh the page to ensure XSRF-TOKEN and Laravel session are strictly active
                        page.goto("https://tradetron.tech/user/dashboard")
                        page.wait_for_load_state("domcontentloaded")
                    except Exception as e:
                        print(f"Warning: page refresh failed: {e}")
                    
                    while True:
                        if last_page and current_page > last_page:
                            break
                            
                        target_url = f"https://tradetron.tech/api/deployed-strategies?tags=&creator_id=&execution=&pnl=&exchange=&instrument_type=&status=&broker_id=&show_nil_qty=yes&per_page=15&type=Self&mode=Pro&statuses=&page={current_page}"
                        
                        api_data = page.evaluate("""async (url) => {
                            const response = await fetch(url, {
                                headers: {
                                    'Accept': 'application/json, text/plain, */*',
                                    'X-Requested-With': 'XMLHttpRequest'
                                }
                            });
                            return response.json();
                        }""", target_url)
                        
                        if api_data and api_data.get("success") and "data" in api_data:
                            page_data = api_data["data"]
                            if last_page is None and "paginate" in api_data:
                                last_page = api_data["paginate"].get("last_page")
                            
                            if not page_data or len(page_data) == 0:
                                break
                                
                            all_strategies.extend(page_data)
                            current_page += 1
                        else:
                            print(f"❌ API fetch failed on page {current_page}. Response: {api_data}")
                            if api_data and api_data.get("message") == "Unauthenticated.":
                                print("\n⚠️ Session expired! Auto-recovering session via get_tradetron_data.py...")
                                import subprocess
                                subprocess.run(["python3", "get_tradetron_data.py"])
                                print("✅ Session auto-recovery complete. Resuming pipeline...\n")
                                time.sleep(5)
                            break
                    
                    if all_strategies:
                        # Fetch WebSocket Token
                        try:
                            token_data = page.evaluate("""async () => {
                                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
                                const response = await fetch('https://tradetron.tech/api/socket/token', {
                                    method: 'POST',
                                    headers: {
                                        'Accept': 'application/json, text/plain, */*',
                                        'X-Requested-With': 'XMLHttpRequest',
                                        'X-CSRF-TOKEN': csrfToken
                                    }
                                });
                                return response.json();
                            }""")
                            if token_data and token_data.get("success") and "data" in token_data:
                                global cached_ws_token
                                cached_ws_token = token_data["data"]
                                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Cached new WebSocket token.")
                            else:
                                print(f"Warning: Token response was unexpected: {token_data}")
                        except Exception as e:
                            print(f"Warning: Failed to fetch WebSocket token: {e}")

                        # Inject baseline all_pnl at market open
                        today_baselines = get_or_create_baselines(all_strategies)
                        for s in all_strategies:
                            strat_id = str(s["id"])
                            s["all_pnl_at_market_open"] = today_baselines.get(strat_id, float(s.get("all_pnl", 0) or 0))

                        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
                        with open(OUTPUT_FILE, 'w') as f:
                            json.dump(all_strategies, f, indent=4)
                        print(f"✅ Pipeline complete: {len(all_strategies)} strategies saved. UI can now read data.json.")
                        
                        # Record the official MTM snapshot from the backend pipeline
                        try:
                            today_pnl_sum = 0.0
                            strategies_pnl = {}
                            for s in all_strategies:
                                if s.get("deployment_type") == "LIVE AUTO":
                                    baseline = s.get("all_pnl_at_market_open", float(s.get("all_pnl", 0) or 0))
                                    pnl = float(s.get("all_pnl", 0) or 0) - baseline
                                    today_pnl_sum += pnl
                                    strat_id = s.get("id")
                                    name = s.get("template", {}).get("name", "Unknown")
                                    run_counter = s.get("run_counter", 0)
                                    broker_name = s.get("strategy_broker", {}).get("broker", {}).get("name", "")
                                    shortcode = get_broker_shortcode(broker_name)
                                    unique_name = f"{strat_id}:{name} ({run_counter} - {shortcode})"
                                    strategies_pnl[unique_name] = pnl
                            record_mtm_snapshot(today_pnl_sum, strategies_pnl)
                        except Exception as e:
                            print(f"Error recording backend MTM snapshot: {e}")
                        
                        # Telegram Notification Logic (Every 30 mins from 9:30 to 15:30)
                        tz = pytz.timezone('Asia/Kolkata')
                        now_tz = datetime.datetime.now(tz)
                        
                        start_time = datetime.time(9, 30)
                        end_time = datetime.time(15, 40) # Grace period up to 15:40 IST
                        
                        if start_time <= now_tz.time() <= end_time:
                            bucket_min = "30" if now_tz.minute >= 30 else "00"
                            current_interval = f"{now_tz.hour:02d}:{bucket_min}"
                            
                            if current_interval != last_telegram_interval:
                                report = generate_telegram_report(all_strategies)
                                if report:
                                    send_telegram_message(report)
                                    print(f"✅ Telegram 30-min report sent for {current_interval} IST")
                                last_telegram_interval = current_interval
                    
                    # If session is invalid, we should re-read cookies from disk on the next cycle
                    if not all_strategies:
                        print("Attempting to reload cookies from disk on next cycle...")
                        with open(COOKIES_FILE, 'r') as f:
                            new_cookies = json.load(f)
                        context.clear_cookies()
                        context.add_cookies(new_cookies)

        except Exception as e:
            print(f"❌ Critical Error in background fetcher (Playwright crashed?): {e}")
            print("Restarting entirely in 10 seconds...")
            time.sleep(10)

def telegram_listener_loop():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    authorized_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not authorized_chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    offset = None
    
    while True:
        try:
            req_url = f"{url}?timeout=30"
            if offset: 
                req_url += f"&offset={offset}"
                
            req = urllib.request.Request(req_url)
            with urllib.request.urlopen(req, timeout=35) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            for result in data.get("result", []):
                offset = result["update_id"] + 1
                message = result.get("message", {})
                text = message.get("text", "")
                chat_id = str(message.get("chat", {}).get("id"))
                
                # Only reply to the authorized user's chat
                if chat_id != authorized_chat_id:
                    continue
                    
                if text.startswith("/report") or text.startswith("/status"):
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Telegram command received: {text}")
                    
                    # Parse optional broker shortcode: /report FT
                    parts = text.strip().split()
                    broker_filter = None
                    if len(parts) >= 2:
                        shortcode = parts[1].upper()
                        broker_map = get_broker_shortcodes()
                        if shortcode in broker_map:
                            broker_filter = broker_map[shortcode]
                        else:
                            available = ", ".join([f"`{k}` = {v}" for k, v in broker_map.items()])
                            send_telegram_message(f"❌ Unknown broker code `{shortcode}`.\n\nAvailable codes:\n{available}")
                            continue
                    
                    if os.path.exists(OUTPUT_FILE):
                        with open(OUTPUT_FILE, 'r') as f:
                            strategies = json.load(f)
                        report = generate_telegram_report(strategies, broker_filter=broker_filter)
                        if report:
                            label = f"— {broker_filter}" if broker_filter else ""
                            send_telegram_message(f"🤖 *Manual Report {label}:*\n\n" + report)
                        else:
                            msg = f"No LIVE AUTO strategies found for {broker_filter}." if broker_filter else "No LIVE AUTO strategies found in current data."
                            send_telegram_message(msg)
                    else:
                        send_telegram_message("Data has not been fetched yet. Please try again in a minute.")
                        
        except Exception as e:
            time.sleep(5)

def git_autopush_loop():
    import subprocess
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [Git Autopush] Thread started. Will check for changes every 5 minutes.")
    while True:
        try:
            # Wait for 300 seconds
            time.sleep(300)
            
            if os.path.exists("git_autopush.sh"):
                res = subprocess.run(["/bin/bash", "git_autopush.sh"], capture_output=True, text=True)
                if res.stdout:
                    for line in res.stdout.strip().split("\n"):
                        if any(phrase in line for phrase in ["Changes detected", "Push completed", "Error", "remote", "remote:", "remote: Error", "remote: Warning", "origin"]):
                            print(f"[Git Autopush] {line}")
                if res.stderr:
                    print(f"[Git Autopush Error] {res.stderr.strip()}")
        except Exception as e:
            print(f"[Git Autopush Exception] {e}")

if __name__ == "__main__":
    # Start the continuous playwright fetcher in a background thread
    fetch_thread = threading.Thread(target=fetch_loop, daemon=True)
    fetch_thread.start()
    
    # Start the Git auto-push daemon
    git_thread = threading.Thread(target=git_autopush_loop, daemon=True)
    git_thread.start()
    
    
    # Start the Telegram command listener
    tg_thread = threading.Thread(target=telegram_listener_loop, daemon=True)
    tg_thread.start()

    # Start the indices scraper in a background thread
    indices_thread = threading.Thread(target=indices_loop, daemon=True)
    indices_thread.start()
    
    # Start the local web server to host the dashboard UI
    port = int(os.environ.get("PORT", 8080))
    server_address = ('', port)
    httpd = HTTPServer(server_address, DashboardHandler)
    print("\n=======================================================")
    print(f"🚀 Tradetron Dashboard Server Running at: http://localhost:{port}")
    print("=======================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
