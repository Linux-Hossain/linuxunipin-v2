from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
import asyncio
from datetime import datetime
import cloudscraper
from bs4 import BeautifulSoup
import re
import json
import os
import uuid
import time
import requests as http_requests
import httpx
from urllib.parse import urlencode

app = FastAPI(
    title="LinuxUniPin v2",
    description="High-performance, automated Free Fire UniPin voucher top-up REST API gateway.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ─── Load Environment Variables (.env) ─────────────────────────────────────────
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# ─── Config ───────────────────────────────────────────────────────────────────
VALID_API_KEYS = {
    "linux-lx0199222",
    "70c9188c-e70e-4eb3-bd50-7d375d2a390c",
}
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

REQUEST_LOG = os.path.join(LOGS_DIR, "requests.json")
RESPONSE_LOG = os.path.join(LOGS_DIR, "responses.json")
PASS_LOG = os.path.join(LOGS_DIR, "pass.json")
TRANSACTION_LOG = os.path.join(LOGS_DIR, "transaction.json")
FAILED_LOG = os.path.join(LOGS_DIR, "failed.json")
ACTIVITY_LOG = os.path.join(LOGS_DIR, "activity.log")
MAX_CODES_PER_ORDER = 5

# ─── Webshare Singapore Proxy Config ──────────────────────────────────────────
WEBSHARE_ENABLED = os.getenv("WEBSHARE_ENABLED", "true").lower() in ("true", "1", "yes")
WEBSHARE_HOST = os.getenv("WEBSHARE_HOST", "p.webshare.io")
WEBSHARE_PORT = os.getenv("WEBSHARE_PORT", "80")
WEBSHARE_USER = os.getenv("WEBSHARE_USER", "cghgkxjs-sg")
WEBSHARE_PASS = os.getenv("WEBSHARE_PASS", "9uvtmzg255yk")
WEBSHARE_COUNTRY = os.getenv("WEBSHARE_COUNTRY", "sg").lower()
PROXY_MODE = os.getenv("PROXY_MODE", "garena_only").lower()  # 'garena_only' or 'all'


def build_webshare_proxy(session_id: str | None = None) -> dict | None:
    """
    Webshare Singapore Rotating Proxy ডিকশনারি রিটার্ন করে।
    """
    if not WEBSHARE_ENABLED or not WEBSHARE_USER or not WEBSHARE_PASS:
        return None

    user_str = WEBSHARE_USER.strip()
    if WEBSHARE_COUNTRY and not any(user_str.lower().endswith(x) for x in [f"-{WEBSHARE_COUNTRY}", f"-{WEBSHARE_COUNTRY}-1", f"-{WEBSHARE_COUNTRY}-2"]):
        user_str = f"{user_str}-{WEBSHARE_COUNTRY}"

    proxy_url = f"http://{user_str}:{WEBSHARE_PASS.strip()}@{WEBSHARE_HOST.strip()}:{WEBSHARE_PORT.strip()}"
    return {
        "http": proxy_url,
        "https": proxy_url
    }




# ─── Package/Denomination List ────────────────────────────────────────────────
DENOM_LIST = {
    "1":  {"name": "25 Diamond",         "payload": '{"name":"25 Diamond","amount":"20.0","amount_uc":"20.0","amount_up":20}'},
    "2":  {"name": "50 Diamond",         "payload": '{"name":"50 Diamond","amount":"36.0","amount_uc":"36.0","amount_up":36}'},
    "3":  {"name": "115 Diamond",        "payload": '{"name":"115 Diamond","amount":"80.0","amount_uc":"80.0","amount_up":80}'},
    "4":  {"name": "240 Diamond",        "payload": '{"name":"240 Diamond","amount":"160.0","amount_uc":"160.0","amount_up":160}'},
    "5":  {"name": "610 Diamond",        "payload": '{"name":"610 Diamond","amount":"405.0","amount_uc":"405.0","amount_up":405}'},
    "6":  {"name": "1240 Diamond",       "payload": '{"name":"1240 Diamond","amount":"810.0","amount_uc":"810.0","amount_up":810}'},
    "7":  {"name": "2530 Diamond",       "payload": '{"name":"2530 Diamond","amount":"1625.0","amount_uc":"1625.0","amount_up":1625}'},
    "8":  {"name": "Weekly Membership",  "payload": '{"name":"Weekly Membership","amount":"161.0","amount_uc":"161.0","amount_up":161}'},
    "9":  {"name": "Monthly Membership", "payload": '{"name":"Monthly Membership","amount":"800.0","amount_uc":"800.0","amount_up":800}'},
    "10": {"name": "Level Up Pass",      "payload": '{"name":"Level Up Pass","amount":"161.0","amount_uc":"161.0","amount_up":161}'},
}

# ─── UniPin Code Prefix → Package ID Map ─────────────────────────────────────
CODE_PREFIX_MAP = {
    # ── 25 Diamond ──────────────────────
    "BDMB-T-S": "1",   # 71 occurrences
    "UPBD-Q-S": "1",   # 112 occurrences
    # ── 50 Diamond ──────────────────────
    "BDMB-U-S": "2",   # 60 occurrences
    "UPBD-R-S": "2",   # 87 occurrences
    # ── 115 Diamond ─────────────────────
    "BDMB-J-S": "3",   # 59 occurrences
    "UPBD-G-S": "3",   # 132 occurrences
    # ── 240 Diamond ─────────────────────
    "BDMB-I-S": "4",   # 138 occurrences
    "UPBD-F-S": "4",   # 180 occurrences
    # ── 610 Diamond ─────────────────────
    "BDMB-K-S": "5",   # 66 occurrences
    "UPBD-H-S": "5",   # 80 occurrences
    # ── 1240 Diamond ────────────────────
    "BDMB-L-S": "6",   # 73 occurrences
    "UPBD-I-S": "6",   # 52 occurrences
    # ── 2530 Diamond ────────────────────
    "BDMB-M-S": "7",   # 137 occurrences
    "UPBD-J-S": "7",   # 167 occurrences
    # ── Weekly Membership ───────────────
    "BDMB-Q-S": "8",   # 386 occurrences
    "UPBD-N-S": "8",   # 1126 occurrences
    # ── Monthly Membership ──────────────
    "BDMB-S-S": "9",   # 471 occurrences
    "UPBD-P-S": "9",   # 651 occurrences
}

# UniPin path_id: কোড কোন UniPin channel-এ submit হবে
PATH_ID_MAP = {
    "BDMB": "659",   # Bangladesh Mobile series
    "UPBD": "670",   # UniPin Bangladesh series
}


def detect_package_id(code: str) -> str | None:
    """
    UniPin voucher code-এর prefix দেখে স্বয়ংক্রিয়ভাবে packageId নির্ধারণ করে।
    Example: 'BDMB-Q-S-15359391 ...' → '8' (Weekly Membership)
    """
    parts = code.strip().split("-")
    if len(parts) >= 3:
        prefix = f"{parts[0]}-{parts[1]}-{parts[2]}"
        return CODE_PREFIX_MAP.get(prefix, None)
    return None


def get_path_id(code: str) -> str:
    """
    UniPin submission-এর জন্য সঠিক path_id নির্ধারণ করে।
    BDMB series → '659', UPBD series → '670', অন্যান্য → '670'
    """
    series = code.strip().split("-")[0].upper()
    return PATH_ID_MAP.get(series, "670")


def extract_api_key(request: Request, data: dict) -> str:
    """
    রিকোয়েস্ট থেকে API Key বের করে।
    Priority: Authorization Header → apiKey (body) → apiKey (query param)
    """
    auth = request.headers.get("Authorization", "").strip()
    if auth:
        return auth.replace("Bearer ", "").strip()
    if data and data.get("apiKey"):
        return str(data["apiKey"]).strip()
    return request.query_params.get("apiKey", "").strip()


def is_valid_api_key(request: Request, data: dict) -> bool:
    key = extract_api_key(request, data)
    return key in VALID_API_KEYS


# ─── Logging ──────────────────────────────────────────────────────────────────

def log_activity(line: str):
    """সহজ এক-লাইনের হিউম্যান রিডেবল লগ ফাইলে লিখে"""
    try:
        with open(ACTIVITY_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[!] Activity Log Error: {e}")

def log_data(filename: str, data: dict):
    """JSON ফাইলে লগ এন্ট্রি যুক্ত করে (সর্বোচ্চ ১০০০টি এন্ট্রি)"""
    try:
        logs = []
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    logs = json.load(f)
                    if not isinstance(logs, list):
                        logs = []
                except json.JSONDecodeError:
                    logs = []
        data_copy = dict(data)
        data_copy["log_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logs.insert(0, data_copy)
        if len(logs) > 1000:
            logs = logs[:1000]
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Log Error ({filename}): {e}")


# ─── Garena Payment Init ──────────────────────────────────────────────────────

# DataDome Token In-Memory Background Cache
_cached_datadome = ""
_cached_datadome_time = 0

def fetch_fresh_datadome_token():
    global _cached_datadome, _cached_datadome_time
    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'desktop': False})
        proxy_dict = build_webshare_proxy(session_id="datadome_worker")
        if proxy_dict:
            scraper.proxies = proxy_dict
        dd_res = scraper.post("https://api-js.datadome.co/js/", data={
            "ddk": "AE3F04AD3F0D3A462481A337485081",
            "Referer": "https://shop.garena.my/",
            "responseFormat": "json"
        }, timeout=(4, 8))
        dd_cookie_raw = dd_res.json().get("cookie", "")
        if "datadome=" in dd_cookie_raw:
            _cached_datadome = dd_cookie_raw.split("datadome=")[1].split(";")[0]
            _cached_datadome_time = time.time()
    except Exception:
        pass


def get_cached_datadome_token(scraper) -> str:
    global _cached_datadome, _cached_datadome_time
    now = time.time()
    if not _cached_datadome or (now - _cached_datadome_time) > 1800:
        fetch_fresh_datadome_token()
    return _cached_datadome


def garena_payment_init(player_id: str, session_id: str | None = None) -> dict:
    """
    Garena শপে লগইন করে UniPin পেমেন্ট ইনিট URL সংগ্রহ করে (Ultra-Fast Streamlined Pipeline)।
    Returns: {"status": "success", "url": ..., "nickname": ..., "region": ...}
             or {"status": "error", "message": ...}
    """
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'android', 'desktop': False}
    )
    proxy_dict = build_webshare_proxy(session_id=session_id)
    if proxy_dict:
        scraper.proxies = proxy_dict

    # Step 0: ডাটাডোম অ্যান্টি-বট কুকি সংগ্রহ (ইন-মেমোরি ক্যাশ্ড)
    datadome_val = get_cached_datadome_token(scraper)
    mspid2 = uuid.uuid4().hex

    # Step 1: সরাসরি Player ID দিয়ে লগইন (হোমপেজ GET ছাড়াই ৩ সেকেন্ড বাঁচানো হয়েছে)
    login_url = "https://shop.garena.my/api/auth/player_id_login"
    login_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7871.124 Mobile Safari/537.36",
        "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Android WebView";v="150"',
        "Content-Type": "application/json",
        "sec-ch-ua-mobile": "?1",
        "Accept": "*/*",
        "Origin": "https://shop.garena.my",
        "X-Requested-With": "mark.via.gp",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://shop.garena.my/",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": f"source=mb; region=SG; language=en; mspid2={mspid2}; datadome={datadome_val}"
    }
    login_payload = {"app_id": 100067, "login_id": player_id}

    try:
        login_res = scraper.post(login_url, headers=login_headers, json=login_payload, timeout=(4, 8))
        login_data = login_res.json()
        login_nickname = login_data.get('nickname', '')
        login_region = login_data.get('region', '')

        if not login_nickname:
            return {"status": "error", "message": "Invalid Player ID or empty nickname"}
    except Exception:
        return {"status": "error", "message": "Login data could not be collected."}

    new_datadome = scraper.cookies.get('datadome', datadome_val) or datadome_val
    session_key = scraper.cookies.get('session_key', '')

    if not session_key:
        return {"status": "error", "message": "Session Key not found."}

    # Step 2: Preflight & CSRF
    preflight_url = "https://shop.garena.my/api/preflight"
    role_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; __csrf__=zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7; datadome={new_datadome}; session_key={session_key}"
    }
    preflight_res = scraper.post(preflight_url, headers=role_headers, timeout=(4, 8))
    set_cookie = preflight_res.headers.get('Set-Cookie', '')
    csrf_match = re.search(r'__csrf__=([^;]+)', set_cookie)
    new_csrf = csrf_match.group(1) if csrf_match else "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"

    # Step 3: Payment Init (UniPin URL আনা)
    pay_init_url = "https://shop.garena.my/api/shop/pay/init?region=MY&language=en"
    pay_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "x-csrf-token": new_csrf,
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; session_key={session_key}; datadome={new_datadome}; __csrf__={new_csrf}"
    }
    pay_payload = {
        "app_id": 100067,
        "packed_role_id": 0,
        "channel_id": 221179,
        "service": "mb",
        "channel_data": {"need_return": True, "payment_channel": None},
        "revamp_experiment": {
            "session_id": mspid2,
            "group": "treatment2",
            "service_version": "mshop_frontend_20260324",
            "source": "mb",
            "domain": "shop.garena.my"
        }
    }

    try:
        final_res = scraper.post(pay_init_url, headers=pay_headers, json=pay_payload, timeout=(4, 8))
        init_url = final_res.json().get('init', {}).get('url', '')
        if init_url:
            return {"status": "success", "url": init_url, "nickname": login_nickname, "region": login_region}
        return {"status": "error", "message": "Init URL not found in response"}
    except Exception:
        return {"status": "error", "message": "Failed to fetch payment init URL"}


def garena_payment_init_batch(player_id: str, count: int = 1, session_id: str | None = None) -> dict:
    """
    Garena শপে ১ বার লগইন করে একসাথে count-সংখ্যক UniPin পেমেন্ট ইনিট URL সংগ্রহ করে।
    (এতে অ্যাকাউন্ট কনকারেন্সি রেস-কন্ডিশন ছাড়াই সব কোডের URL ১.৫-২ সেকেন্ডে রেডি হয়)
    """
    if count <= 1:
        res = garena_payment_init(player_id, session_id=session_id)
        if res.get("status") == "success":
            return {
                "status": "success",
                "urls": [res.get("url")],
                "nickname": res.get("nickname"),
                "region": res.get("region")
            }
        return res

    for attempt in range(2):
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'android', 'desktop': False}
        )
        proxy_dict = build_webshare_proxy(session_id=session_id or f"batch_{attempt}")
        if proxy_dict:
            scraper.proxies = proxy_dict

        datadome_val = get_cached_datadome_token(scraper)
        mspid2 = uuid.uuid4().hex

        login_url = "https://shop.garena.my/api/auth/player_id_login"
        login_headers = {
            "Host": "shop.garena.my",
            "Connection": "keep-alive",
            "sec-ch-ua-platform": '"Android"',
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7871.124 Mobile Safari/537.36",
            "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Android WebView";v="150"',
            "Content-Type": "application/json",
            "sec-ch-ua-mobile": "?1",
            "Accept": "*/*",
            "Origin": "https://shop.garena.my",
            "X-Requested-With": "mark.via.gp",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://shop.garena.my/",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": f"source=mb; region=SG; language=en; mspid2={mspid2}; datadome={datadome_val}"
        }
        login_payload = {"app_id": 100067, "login_id": player_id}

        try:
            login_res = scraper.post(login_url, headers=login_headers, json=login_payload, timeout=(4, 8))
            login_data = login_res.json()
            login_nickname = login_data.get('nickname', '')
            login_region = login_data.get('region', '')
            if not login_nickname:
                if attempt == 0:
                    time.sleep(0.3)
                    continue
                return {"status": "error", "message": "Invalid Player ID or empty nickname"}
        except Exception:
            if attempt == 0:
                time.sleep(0.3)
                continue
            return {"status": "error", "message": "Login data could not be collected."}

        new_datadome = scraper.cookies.get('datadome', datadome_val) or datadome_val
        session_key = scraper.cookies.get('session_key', '')
        if not session_key:
            if attempt == 0:
                time.sleep(0.3)
                continue
            return {"status": "error", "message": "Session Key not found."}

        preflight_url = "https://shop.garena.my/api/preflight"
        role_headers = {
            "Host": "shop.garena.my",
            "Connection": "keep-alive",
            "sec-ch-ua-platform": '"Android"',
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; __csrf__=zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7; datadome={new_datadome}; session_key={session_key}"
        }
        try:
            preflight_res = scraper.post(preflight_url, headers=role_headers, timeout=(4, 8))
            set_cookie = preflight_res.headers.get('Set-Cookie', '')
            csrf_match = re.search(r'__csrf__=([^;]+)', set_cookie)
            new_csrf = csrf_match.group(1) if csrf_match else "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"
        except Exception:
            new_csrf = "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"

        # Parallel pay inits for `count` URLs
        pay_init_url = "https://shop.garena.my/api/shop/pay/init?region=MY&language=en"
        pay_headers = {
            "Host": "shop.garena.my",
            "Connection": "keep-alive",
            "sec-ch-ua-platform": '"Android"',
            "x-csrf-token": new_csrf,
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; session_key={session_key}; datadome={new_datadome}; __csrf__={new_csrf}"
        }
        pay_payload = {
            "app_id": 100067,
            "packed_role_id": 0,
            "channel_id": 221179,
            "service": "mb",
            "channel_data": {"need_return": True, "payment_channel": None},
            "revamp_experiment": {
                "session_id": mspid2,
                "group": "treatment2",
                "service_version": "mshop_frontend_20260324",
                "source": "mb",
                "domain": "shop.garena.my"
            }
        }

        def fetch_single_pay_url(idx_i):
            try:
                final_res = scraper.post(pay_init_url, headers=pay_headers, json=pay_payload, timeout=(4, 8))
                return final_res.json().get('init', {}).get('url', '')
            except Exception:
                return ''

        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as executor:
            urls = list(executor.map(fetch_single_pay_url, range(count)))

        valid_urls = [u for u in urls if u]
        if len(valid_urls) == count:
            return {
                "status": "success",
                "urls": urls,
                "nickname": login_nickname,
                "region": login_region
            }
        elif len(valid_urls) > 0:
            return {
                "status": "success",
                "urls": urls,
                "nickname": login_nickname,
                "region": login_region
            }
        elif attempt == 0:
            time.sleep(0.3)
            continue
        return {"status": "error", "message": "Failed to fetch payment init URLs"}

    return {"status": "error", "message": "Garena init failed"}


# ─── UniPin Voucher Redeem ────────────────────────────────────────────────────

def execute_redeem(input_url: str, packageId: str, user_input: str, session_id: str | None = None) -> dict:
    """
    UniPin-এ ভাউচার সিরিয়াল ও পিন সাবমিট করে রিডিম করে (Ultra-Fast 2-Step Flow)।
    Returns: {"status": "success", "details": {...}}
             or {"status": "error", "message": ...}
    """
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'desktop': False})
    if PROXY_MODE == "all":
        proxy_dict = build_webshare_proxy(session_id=session_id)
        if proxy_dict:
            scraper.proxies = proxy_dict

    match = re.search(r'/unibox/d/([^?]+)', input_url)
    if not match:
        return {"status": "error", "message": "Invalid Unique ID in URL"}
    unique_id = match.group(1)

    try:
        # Step 1: সরাসরি Denomination সিলেকশন পেজ লোড (মাঝের অপ্রয়োজনীয় হোমপেজ GET বাদ)
        denom_page_url = f"https://www.unipin.com/unibox/select_denom/{unique_id}?lg=en"
        headers_get = {
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": "https://shop.garena.my/"
        }
        res_denom = scraper.get(denom_page_url, headers=headers_get, timeout=(4, 8))

        # Fast Regex CSRF Token Extraction
        match_csrf = re.search(r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', res_denom.text) or re.search(r'content=["\']([^"\']+)["\']\s+name=["\']csrf-token["\']', res_denom.text)
        meta_token = match_csrf.group(1) if match_csrf else None
        if not meta_token:
            soup2 = BeautifulSoup(res_denom.text, 'html.parser')
            meta_tag = soup2.find('meta', {'name': 'csrf-token'})
            if meta_tag:
                meta_token = meta_tag['content']

        if not meta_token:
            return {"status": "error", "message": "csrf-token meta tag not found!"}

        # Step 2: Denomination সিলেক্ট করে POST
        headers_post = {
            "origin": "https://www.unipin.com",
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "referer": denom_page_url
        }
        payload_denom = {"_token": meta_token, "denomination": DENOM_LIST[packageId]['payload']}
        scraper.post(denom_page_url, data=payload_denom, headers=headers_post, timeout=(4, 8))

        # Step 3: সিরিয়াল ও পিন পার্স
        parts = user_input.strip().split(" ")
        if len(parts) < 2:
            return {"status": "error", "message": "Invalid code format. Expected 'SERIAL PIN'"}
        clean_serial = parts[0].replace("-", "")
        pin_parts = parts[1].split("-")
        if len(pin_parts) < 4:
            return {"status": "error", "message": "Invalid PIN format. Expected 4 PIN parts separated by hyphens"}
        path_id = get_path_id(user_input)

        # Step 4: সরাসরি ভাউচার সাবমিট (Final POST — মাঝের ৩টি অপ্রয়োজনীয় GET পেজ বাদ)
        final_post_url = f"https://www.unipin.com/unibox/c/{unique_id}/{path_id}"
        headers_final = {
            "origin": "https://www.unipin.com",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"https://www.unipin.com/unibox/c/{unique_id}/{path_id}?b=1"
        }
        final_payload = {
            "_token": meta_token,
            "serial": clean_serial,
            "pin_1": pin_parts[0],
            "pin_2": pin_parts[1],
            "pin_3": pin_parts[2],
            "pin_4": pin_parts[3]
        }

        final_res = scraper.post(final_post_url, data=urlencode(final_payload), headers=headers_final, timeout=(4, 8))

        # Step 5: রেজাল্ট দ্রুত পার্স (Fast Regex + Fallback)
        if "Transaction successful" in final_res.text:
            def fast_get(label_pattern):
                m = re.search(rf'{label_pattern}.*?<div[^>]*class=["\']details-value["\'][^>]*>(.*?)</div>', final_res.text, re.IGNORECASE | re.DOTALL)
                return m.group(1).strip() if m else None

            trans_id_m = re.search(r'id=["\']trans_id["\'][^>]*>(.*?)<', final_res.text)
            trans_no = trans_id_m.group(1).strip() if trans_id_m else "N/A"

            date_val = fast_get("Transaction Date") or "N/A"
            ref_val = fast_get("Reference") or "N/A"
            item_val = fast_get("Item") or "N/A"
            amt_val = fast_get("Transaction Amount") or "N/A"

            if date_val == "N/A" or trans_no == "N/A":
                final_soup = BeautifulSoup(final_res.text, 'html.parser')
                def get_val(label_text):
                    label = final_soup.find('div', class_='details-label', string=re.compile(label_text, re.I))
                    if label:
                        val = label.find_next_sibling('div', class_='details-value')
                        return val.get_text(strip=True) if val else "N/A"
                    return "N/A"
                trans_id = final_soup.find(id='trans_id')
                trans_no = trans_id.get_text(strip=True) if trans_id else trans_no
                date_val = get_val('Transaction Date') if date_val == "N/A" else date_val
                ref_val = get_val('Reference') if ref_val == "N/A" else ref_val
                item_val = get_val('Item') if item_val == "N/A" else item_val
                amt_val = get_val('Transaction Amount') if amt_val == "N/A" else amt_val

            details = {
                "date": date_val,
                "trans_no": trans_no,
                "reference": ref_val,
                "item": item_val,
                "amount": amt_val
            }
            return {"status": "success", "details": details}

        elif "validationError" in final_res.text or "alert-danger" in final_res.text:
            err_m = re.search(r'<div[^>]*class=["\']alert alert-danger["\'][^>]*>(.*?)</div>', final_res.text, re.DOTALL)
            return {"status": "error", "message": err_m.group(1).strip() if err_m else 'Invalid Serial'}

        elif "Consumed%20Voucher" in final_res.text or "Consumed Voucher" in final_res.text:
            return {"status": "error", "message": "Consumed Voucher (Already Used)"}

        else:
            msg_m = re.search(r'<h1[^>]*class=["\']title-case-0["\'][^>]*>(.*?)</h1>', final_res.text, re.DOTALL)
            return {"status": "error", "message": msg_m.group(1).strip() if msg_m else 'Unknown Error'}

    except Exception as e:
        return {"status": "error", "message": str(e)}

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Worker Function ─────────────────────────────────────────────────────────

def process_single_code(args_tuple: tuple) -> tuple:
    """
    একটি একক কোডের জন্য Garena Session Init ও UniPin Redeem সম্পন্ন করে।
    asyncio.to_thread দিয়ে parallel worker thread এ চলে।
    """
    try:
        idx, code, uid, fallback_package_id = args_tuple
        code = code.strip()
        if not code:
            return idx, None, False, "N/A", "N/A"

        pkg = detect_package_id(code) or fallback_package_id
        if not pkg or pkg not in DENOM_LIST:
            batch_item = {
                "uc": code,
                "ok": False,
                "detail": "❌ Undetected or invalid package ID"
            }
            return idx, batch_item, False, "N/A", "N/A"

        # Unique sticky session id for this transaction
        sub_session_id = uuid.uuid4().hex[:8]

        # Garena সেশন ইনিট
        init_res = garena_payment_init(str(uid), session_id=sub_session_id)

        if init_res.get("status") == "error":
            msg = init_res.get("message", "Garena init failed")
            batch_item = {
                "uc": code,
                "ok": False,
                "detail": f"❌ {msg}"
            }
            return idx, batch_item, False, "N/A", "N/A"

        nick = init_res.get("nickname", "N/A")
        reg  = init_res.get("region", "N/A")

        # ভাউচার রিডিম
        redeem_res = execute_redeem(init_res.get("url", ""), pkg, code, session_id=sub_session_id)
        ok = redeem_res.get("status") == "success"

        if ok:
            detail = "✅ Success"
            trx_id = redeem_res.get("details", {}).get("trans_no", None)
            batch_item = {"uc": code, "ok": ok, "detail": detail}
            if trx_id and trx_id != "N/A":
                batch_item["trx_id"] = trx_id
            if redeem_res.get("details"):
                batch_item["receipt"] = redeem_res["details"]
        else:
            msg = redeem_res.get("message", "Failed")
            detail = f"❌ {msg}"
            batch_item = {"uc": code, "ok": ok, "detail": detail}

        return idx, batch_item, ok, nick, reg
    except Exception as e:
        code_val = code if 'code' in locals() else "N/A"
        idx_val = idx if 'idx' in locals() else 0
        batch_item = {
            "uc": code_val,
            "ok": False,
            "detail": f"❌ Error: {str(e)}"
        }
        return idx_val, batch_item, False, "N/A", "N/A"


# ─── Async Batch Processor ────────────────────────────────────────────────────

async def process_batch(uid: str, packageId: str, codes: list, orderid: str) -> dict:
    """
    একাধিক UniPin ভাউচার কোড asyncio.gather ও to_thread দিয়ে একযোগে প্রসেস করে batch রেজাল্ট রিটার্ন করে।
    (৩-৫ গুণ ফাস্ট)
    একাধিক UniPin ভাউচার কোড ১টি মাত্র Garena সেশনে প্যারালাল URL সংগ্রহ করে
    এবং একযোগে UniPin Redeem সম্পন্ন করে ৩.৫ সেকেন্ডে কমপ্লিট করে।
    """
    valid_tasks = [(i, code, uid, packageId) for i, code in enumerate(codes) if code.strip()]
    valid_tasks = [(i, code.strip(), packageId) for i, code in enumerate(codes) if code.strip()]

    if not valid_tasks:
        return {
            "status": "failed",
            "orderid": orderid,
            "nickname": "N/A",
            "username": "N/A",
            "region": "N/A",
            "success": 0,
            "failed": 0,
            "total": 0,
            "batch": []
        }

    raw_results = [None] * len(valid_tasks)
    success_count = 0
    fail_count    = 0
    nickname      = "N/A"
    region        = "N/A"

    if len(valid_tasks) == 1:
        idx, item, ok, nick, reg = await asyncio.to_thread(process_single_code, valid_tasks[0])
        raw_results[0] = item
        if ok:
            success_count += 1
        else:
    # Step 1: ১টি ফ্রেশ প্রক্সি সেশনে Garena থেকে সব কোডের URL একসাথে সংগ্রহ করো (~১.৮ সেকেন্ড)
    init_res = await asyncio.to_thread(garena_payment_init_batch, str(uid), len(valid_tasks))

    if init_res.get("status") == "error":
        msg = init_res.get("message", "Garena init failed")
        for i, code, _ in valid_tasks:
            raw_results[i] = {
                "uc": code,
                "ok": False,
                "detail": f"❌ {msg}"
            }
            fail_count += 1
        if nick != "N/A": nickname = nick
        if reg != "N/A":  region = reg
    else:
        # একাধিক কোড (২-৫টি) থাকলে asyncio.gather + asyncio.to_thread দিয়ে প্যারালালে প্রসেস করো
        tasks = [asyncio.to_thread(process_single_code, task) for task in valid_tasks]
        task_outputs = await asyncio.gather(*tasks)
        nickname = init_res.get("nickname", "N/A")
        region = init_res.get("region", "N/A")
        urls = init_res.get("urls", [])

        for idx, item, ok, nick, reg in task_outputs:
        # Step 2: সব কোডের UniPin Redeem সম্পূর্ণ প্যারালালে ডিরেক্ট সাবমিট করো (~১.১ সেকেন্ড)
        def redeem_worker(item_tuple):
            idx, code, default_pkg, u_url = item_tuple
            pkg = detect_package_id(code) or default_pkg
            if not pkg or pkg not in DENOM_LIST:
                return idx, {"uc": code, "ok": False, "detail": "❌ Undetected or invalid package ID"}, False
            if not u_url:
                return idx, {"uc": code, "ok": False, "detail": "❌ Failed to acquire payment gateway URL"}, False

            redeem_res = execute_redeem(u_url, pkg, code)
            ok = redeem_res.get("status") == "success"
            if ok:
                detail = "✅ Success"
                trx_id = redeem_res.get("details", {}).get("trans_no", None)
                batch_item = {"uc": code, "ok": ok, "detail": detail}
                if trx_id and trx_id != "N/A":
                    batch_item["trx_id"] = trx_id
                if redeem_res.get("details"):
                    batch_item["receipt"] = redeem_res["details"]
            else:
                msg = redeem_res.get("message", "Failed")
                batch_item = {"uc": code, "ok": ok, "detail": f"❌ {msg}"}
            return idx, batch_item, ok

        worker_items = [
            (task[0], task[1], task[2], urls[i] if i < len(urls) else "")
            for i, task in enumerate(valid_tasks)
        ]

        redeem_tasks = [asyncio.to_thread(redeem_worker, item) for item in worker_items]
        redeem_outputs = await asyncio.gather(*redeem_tasks)

        for idx, item, ok in redeem_outputs:
            raw_results[idx] = item
            if ok:
                success_count += 1
            else:
                fail_count += 1
            if nick != "N/A": nickname = nick
            if reg != "N/A":  region = reg

    batch_results = [b for b in raw_results if b is not None]
    total = len(batch_results)

    if total == 0:
        status = "failed"
    elif success_count == total:
        status = "success"
    elif success_count > 0:
        status = "partial"
    else:
        status = "failed"

    result = {
        "status": status,
        "orderid": orderid,
        "nickname": nickname,
        "username": nickname,  # UcBot field alias
        "region": region,
        "success": success_count,
        "failed": fail_count,
        "total": total,
        "batch": batch_results
    }

    log_entry = {
        "orderid": orderid,
        "uid": uid,
        "nickname": nickname,
        "region": region,
        "package": DENOM_LIST.get(packageId, {}).get("name", "Unknown"),
        "total_codes": total,
        "success": success_count,
        "failed": fail_count,
        "status": status,
        "batch": batch_results
    }
    if status == "success":
        log_data(PASS_LOG, log_entry)
        log_data(TRANSACTION_LOG, log_entry)
    elif status == "partial":
        log_data(PASS_LOG, log_entry)
        log_data(FAILED_LOG, log_entry)
        log_data(TRANSACTION_LOG, log_entry)
    else:
        log_data(FAILED_LOG, log_entry)

    # 1-Line Clean Activity Logging for Easy Exploration
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary_item = batch_results[0] if batch_results else {}
    trx_str = summary_item.get("trx_id") or summary_item.get("receipt", {}).get("trans_no", "")
    code_str = summary_item.get("uc", "")
    pkg_name = DENOM_LIST.get(packageId, {}).get("name", "Unknown")
    detail_str = summary_item.get("detail", "")

    if status == "success":
        log_activity(f"[{now_str}] [PASS] Order: {orderid} | UID: {uid} ({nickname}) | Pkg: {pkg_name} | Code: {code_str} | Trx: {trx_str}")
    elif status == "partial":
        log_activity(f"[{now_str}] [PARTIAL] Order: {orderid} | UID: {uid} ({nickname}) | Pkg: {pkg_name} | Success: {success_count}/{total}")
    else:
        log_activity(f"[{now_str}] [FAIL] Order: {orderid} | UID: {uid} ({nickname}) | Pkg: {pkg_name} | Code: {code_str} | {detail_str}")

    return result


async def send_callback(callback_url: str, payload: dict):
    """Async HTTPX দিয়ে Callback URL-এ POST পাঠায়"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(callback_url, json=payload)
    except Exception as e:
        print(f"[!] Callback Error to {callback_url}: {e}")


def parse_codes_input(raw_code) -> list:
    """
    বিভিন্ন ফরম্যাটের (কমা-সেপারেটেড, নিউলাইন-সেপারেটেড, অথবা JSON লিস্ট) কোড ইনপুট ক্লিন পার্স করে।
    """
    if isinstance(raw_code, list):
        return [str(c).strip() for c in raw_code if str(c).strip()]
    if isinstance(raw_code, str):
        return [c.strip() for c in re.split(r'[\n\r,]+', raw_code) if c.strip()]
    return []


async def get_request_data(request: Request) -> dict:
    """JSON, Form বা Query parameters থেকে data বের করে unified dict তৈরি করে"""
    data = {}
    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = await request.json()
            except Exception:
                data = {}
        elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            try:
                form = await request.form()
                data = dict(form)
            except Exception:
                data = {}
        else:
            try:
                data = await request.json()
            except Exception:
                try:
                    form = await request.form()
                    data = dict(form)
                except Exception:
                    data = {}

    for k, v in request.query_params.items():
        if k not in data:
            data[k] = v

    return data


async def async_background_wrapper(uid: str, package_id: str, codes: list, orderid: str, callback_url: str):
    t_start = time.time()
    result = await process_batch(uid, package_id, codes, orderid)
    duration_ms = round((time.time() - t_start) * 1000, 2)
    resp_log_entry = {
        "orderid": orderid,
        "endpoint": "/api/unipin/async",
        "duration_ms": f"{duration_ms} ms",
        "response": result
    }
    log_data(RESPONSE_LOG, resp_log_entry)
    await send_callback(callback_url, result)


# ─── FastAPI Routes ───────────────────────────────────────────────────────────

@app.api_route("/api/unipin", methods=["GET", "POST"])
@app.api_route("/topup-sync", methods=["GET", "POST"])
async def unipin_api(request: Request):
    """
    Sync TopUp Endpoint — তাৎক্ষণিক রেজাল্ট রিটার্ন করে।
    """
    t_start = time.time()
    data = await get_request_data(request)

    if not is_valid_api_key(request, data):
        return JSONResponse(content={"status": "error", "message": "Invalid API Key."}, status_code=401)

    uid      = data.get("uid") or data.get("playerid")
    raw_code = data.get("code", "")
    orderid  = data.get("orderid") or f"FLX-{str(uuid.uuid4())[:8].upper()}"

    if not uid or not raw_code:
        return JSONResponse(content={"status": "error", "message": "Missing required fields: uid, code"}, status_code=400)

    codes = parse_codes_input(raw_code)
    if len(codes) == 0:
        return JSONResponse(content={"status": "error", "message": "No valid codes provided."}, status_code=400)
    if len(codes) > MAX_CODES_PER_ORDER:
        return JSONResponse(content={"status": "error", "message": f"Max {MAX_CODES_PER_ORDER} codes per order. You sent {len(codes)}."}, status_code=400)

    package_id = str(data.get("packageId", "")).strip()
    if not package_id:
        package_id = detect_package_id(codes[0])
    if not package_id or package_id not in DENOM_LIST:
        return JSONResponse(content={"status": "error", "message": "Cannot detect product from code prefix. Please provide packageId (1-9)."}, status_code=400)

    client_ip = request.client.host if request.client else "unknown"
    req_log_entry = {
        "orderid": orderid,
        "endpoint": "/api/unipin",
        "client_ip": client_ip,
        "uid": uid,
        "package_id": package_id,
        "codes_count": len(codes),
        "payload": {k: v for k, v in data.items() if k != "apiKey"}
    }
    log_data(REQUEST_LOG, req_log_entry)

    result = await process_batch(uid, package_id, codes, orderid)
    duration_ms = round((time.time() - t_start) * 1000, 2)
    resp_log_entry = {
        "orderid": orderid,
        "endpoint": "/api/unipin",
        "duration_ms": f"{duration_ms} ms",
        "response": result
    }
    log_data(RESPONSE_LOG, resp_log_entry)

    return JSONResponse(content=result, status_code=200)


@app.api_route("/api/unipin/async", methods=["POST"])
@app.api_route("/topup", methods=["POST"])
async def unipin_async(request: Request, background_tasks: BackgroundTasks):
    """
    Async TopUp Endpoint — তাৎক্ষণিক 202 Accepted রিটার্ন করে,
    প্রসেস শেষে Webhook Callback URL-এ POST পাঠায়।
    """
    data = await get_request_data(request)

    if not is_valid_api_key(request, data):
        return JSONResponse(content={"status": "error", "message": "Invalid API Key."}, status_code=401)

    uid          = data.get("uid") or data.get("playerid")
    raw_code     = data.get("code", "")
    callback_url = data.get("url", "")
    orderid      = data.get("orderid") or f"FLX-{str(uuid.uuid4())[:8].upper()}"

    if not uid or not raw_code:
        return JSONResponse(content={"status": "error", "message": "Missing required fields: uid, code"}, status_code=400)

    if not callback_url:
        return JSONResponse(content={"status": "error", "message": "Missing required field: url (callback URL)"}, status_code=400)

    codes = parse_codes_input(raw_code)
    if len(codes) == 0:
        return JSONResponse(content={"status": "error", "message": "No valid codes provided."}, status_code=400)
    if len(codes) > MAX_CODES_PER_ORDER:
        return JSONResponse(content={"status": "error", "message": f"Max {MAX_CODES_PER_ORDER} codes per order."}, status_code=400)

    package_id = str(data.get("packageId", "")).strip()
    if not package_id:
        package_id = detect_package_id(codes[0])
    if not package_id or package_id not in DENOM_LIST:
        return JSONResponse(content={"status": "error", "message": "Cannot detect product from code prefix. Please provide packageId (1-9)."}, status_code=400)

    client_ip = request.client.host if request.client else "unknown"
    req_log_entry = {
        "orderid": orderid,
        "endpoint": "/api/unipin/async",
        "client_ip": client_ip,
        "uid": uid,
        "package_id": package_id,
        "codes_count": len(codes),
        "callback_url": callback_url,
        "payload": {k: v for k, v in data.items() if k != "apiKey"}
    }
    log_data(REQUEST_LOG, req_log_entry)

    background_tasks.add_task(async_background_wrapper, uid, package_id, codes, orderid, callback_url)

    return JSONResponse(content={"status": "accepted", "orderid": orderid}, status_code=202)


@app.get("/api/history")
async def api_history(request: Request):
    """
    অর্ডার ও সিস্টেম হিস্টোরি দেখায়।
    GET /api/history?apiKey=linux-lx0199222&type=pass|failed|requests|responses|all&limit=50
    """
    data = dict(request.query_params)
    if not is_valid_api_key(request, data):
        return JSONResponse(content={"status": "error", "message": "Invalid API Key."}, status_code=401)

    limit    = min(int(request.query_params.get("limit", 50)), 200)
    log_type = request.query_params.get("type", "all").lower()

    all_logs = []

    def load_log_file(fn):
        if os.path.exists(fn):
            try:
                with open(fn, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    if log_type in ("all", "pass", "success"):
        all_logs.extend(load_log_file(PASS_LOG))
    if log_type in ("all", "failed"):
        all_logs.extend(load_log_file(FAILED_LOG))
    if log_type in ("requests",):
        all_logs.extend(load_log_file(REQUEST_LOG))
    if log_type in ("responses",):
        all_logs.extend(load_log_file(RESPONSE_LOG))
    if log_type in ("transaction", "transactions"):
        all_logs.extend(load_log_file(TRANSACTION_LOG))

    all_logs.sort(key=lambda x: x.get("log_time", ""), reverse=True)
    all_logs = all_logs[:limit]

    return JSONResponse(content={
        "status": "success",
        "type": log_type,
        "total": len(all_logs),
        "history": all_logs
    })


@app.get("/api/proxy/status")
async def api_proxy_status(request: Request):
    """
    Webshare Proxy কানেকশন, আইপি এবং স্পিড/ল্যাটেন্সি টেস্ট এন্ডপয়েন্ট।
    """
    data = dict(request.query_params)
    if not is_valid_api_key(request, data):
        return JSONResponse(content={"status": "error", "message": "Invalid API Key."}, status_code=401)

    if not WEBSHARE_ENABLED or not WEBSHARE_USER or not WEBSHARE_PASS:
        return JSONResponse(content={
            "status": "disabled",
            "message": "Webshare Proxy is currently disabled or credentials not set in .env",
            "proxy_enabled": WEBSHARE_ENABLED,
            "proxy_mode": PROXY_MODE
        })

    proxy_info = build_webshare_proxy(session_id="test")
    t0 = time.time()
    try:
        async with httpx.AsyncClient(proxy=proxy_info["http"], timeout=10.0) as client:
            resp = await client.get("http://ip-api.com/json")
            latency_ms = round((time.time() - t0) * 1000, 2)
            ip_data = resp.json()
            return JSONResponse(content={
                "status": "success",
                "message": "Webshare Proxy is active and connected!",
                "latency_ms": f"{latency_ms} ms",
                "proxy_mode": PROXY_MODE,
                "ip": ip_data.get("query"),
                "country": ip_data.get("country"),
                "countryCode": ip_data.get("countryCode"),
                "city": ip_data.get("city"),
                "isp": ip_data.get("isp")
            })
    except Exception as e:
        latency_ms = round((time.time() - t0) * 1000, 2)
        return JSONResponse(content={
            "status": "error",
            "message": f"Proxy connection failed: {str(e)}",
            "latency_ms": f"{latency_ms} ms",
            "proxy_mode": PROXY_MODE
        }, status_code=500)



# ─── Home / Dashboard ─────────────────────────────────────────────────────────

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LinuxUniPin v2 — Free Fire TopUp API Documentation</title>
    <meta name="description" content="High-performance, automated Free Fire UniPin voucher top-up REST API gateway.">
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Fira+Code:wght@400;500;600&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Plus Jakarta Sans', 'sans-serif'],
                        display: ['Space Grotesk', 'sans-serif'],
                        mono: ['Fira Code', 'monospace'],
                    },
                    colors: {
                        cyber: {
                            50: '#ecfdf5',
                            500: '#10b981',
                            600: '#059669',
                            900: '#064e3b',
                            950: '#022c22',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body { background-color: #050811; font-family: 'Plus Jakarta Sans', sans-serif; }
        .glass-card {
            background: rgba(13, 20, 36, 0.75);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(16, 185, 129, 0.15);
        }
        .glass-card:hover {
            border-color: rgba(16, 185, 129, 0.35);
        }
        .glow-emerald {
            box-shadow: 0 0 35px -8px rgba(16, 185, 129, 0.25);
        }
        .glow-cyan {
            box-shadow: 0 0 35px -8px rgba(6, 182, 212, 0.25);
        }
        .text-gradient {
            background: linear-gradient(135deg, #10b981 0%, #06b6d4 50%, #a855f7 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        pre code { font-family: 'Fira Code', monospace; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #070b14; }
        ::-webkit-scrollbar-thumb { background: #1f293d; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #10b981; }
    </style>
</head>
<body class="text-slate-100 min-h-screen selection:bg-emerald-500 selection:text-slate-950">

    <!-- Sticky Header -->
    <header class="sticky top-0 z-50 glass-card border-b border-emerald-500/20 bg-slate-950/80 backdrop-blur-2xl">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-500 flex items-center justify-center text-slate-950 font-black font-display text-lg shadow-lg shadow-emerald-500/20">
                    ⚡
                </div>
                <div>
                    <span class="font-display font-extrabold text-base sm:text-lg tracking-tight text-slate-100">LinuxUniPin <span class="text-gradient">v2</span></span>
                    <span class="hidden sm:inline-block text-[10px] uppercase font-mono px-2 py-0.5 ml-2 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">v2.0 FastAPI</span>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <a href="/docs" target="_blank" class="px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-mono text-emerald-400 hover:bg-emerald-500/20 transition-all flex items-center gap-1.5">
                    📖 Swagger Docs
                </a>
                <a href="https://github.com/Linux-Hossain/linuxunipin-v2" target="_blank" class="px-3.5 py-1.5 rounded-xl bg-slate-900 border border-slate-700/80 text-xs font-semibold hover:border-emerald-500/50 transition-all flex items-center gap-2 text-slate-300 hover:text-white">
                    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/></svg>
                    GitHub
                </a>
            </div>
        </div>
    </header>

    <!-- Hero Banner -->
    <div class="relative overflow-hidden border-b border-slate-900 bg-gradient-to-b from-emerald-950/20 via-slate-950 to-slate-950">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-14 relative z-10">
            <div class="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold tracking-wide mb-4">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                Fastest UniPin Voucher API Gateway (FastAPI + Asyncio Engine)
            </div>
            <h1 class="text-3xl sm:text-5xl font-display font-extrabold text-slate-100 tracking-tight leading-tight">
                Free Fire TopUp <span class="text-gradient">API Documentation</span>
            </h1>
            <p class="text-slate-400 text-sm sm:text-base max-w-2xl mt-3 leading-relaxed">
                Automated, high-concurrency REST API for UniPin Bangladesh voucher redemptions. Powered by FastAPI & Asyncio parallel tasks for 3-5x faster batch order processing.
            </p>
            
            <!-- Base URL Box -->
            <div class="mt-6 p-4 glass-card rounded-2xl glow-emerald max-w-2xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div class="space-y-1">
                    <span class="text-[11px] font-mono uppercase tracking-wider text-emerald-400 font-bold">Base URL</span>
                    <code class="text-slate-200 font-mono text-sm block">https://linuxunipin-v2.vercel.app</code>
                </div>
                <div class="flex gap-2">
                    <button onclick="copyToClipboard('https://linuxunipin-v2.vercel.app')" class="px-3.5 py-2 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-semibold transition-all flex items-center gap-1.5">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"/></svg>
                        Copy URL
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Main Container -->
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        <div class="grid grid-cols-1 lg:grid-cols-4 gap-8">
            
            <!-- Left Navigation (Desktop) -->
            <aside class="hidden lg:block lg:col-span-1">
                <div class="sticky top-24 space-y-1 glass-card p-4 rounded-2xl">
                    <p class="text-[11px] font-mono uppercase font-bold text-slate-400 px-3 pb-2 border-b border-slate-800 mb-2">Documentation Menu</p>
                    <a href="#overview" class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20">
                        ⚡ Overview & Features
                    </a>
                    <a href="#auth" class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-emerald-400 hover:bg-slate-900 transition-all">
                        🔑 Authentication
                    </a>
                    <a href="#sync-topup" class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-emerald-400 hover:bg-slate-900 transition-all">
                        🚀 Sync Topup (Direct)
                    </a>
                    <a href="#async-topup" class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-emerald-400 hover:bg-slate-900 transition-all">
                        🔄 Async Topup (Webhook)
                    </a>
                    <a href="#prefix-map" class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-emerald-400 hover:bg-slate-900 transition-all">
                        🎯 Auto Package Mapping
                    </a>
                    <a href="#status-codes" class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-emerald-400 hover:bg-slate-900 transition-all">
                        🚦 HTTP Response Codes
                    </a>
                </div>
            </aside>

            <!-- Right Content Area -->
            <main class="lg:col-span-3 space-y-8">
                
                <!-- Overview -->
                <section id="overview" class="glass-card p-6 rounded-2xl glow-emerald">
                    <h2 class="text-xl font-display font-bold text-slate-100 flex items-center gap-2 mb-4 border-b border-slate-800 pb-3">
                        <span class="text-emerald-400">⚡</span> Overview & Highlights
                    </h2>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div class="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                            <span class="text-2xl mb-2 block">🚀</span>
                            <h3 class="font-bold text-sm text-slate-200">Asyncio Concurrency</h3>
                            <p class="text-xs text-slate-400 mt-1">Multi-code batch orders execute simultaneously using asyncio.gather (~3-4s for 2-5 codes).</p>
                        </div>
                        <div class="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                            <span class="text-2xl mb-2 block">🎯</span>
                            <h3 class="font-bold text-sm text-slate-200">Auto Package Detect</h3>
                            <p class="text-xs text-slate-400 mt-1">No need to specify packageId manually. Automatically identifies 18 code prefix types.</p>
                        </div>
                        <div class="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                            <span class="text-2xl mb-2 block">🧾</span>
                            <h3 class="font-bold text-sm text-slate-200">Full Receipts & TRX</h3>
                            <p class="text-xs text-slate-400 mt-1">Returns Garena / UniPin trans_no, date, reference, item name, and amount for every success item.</p>
                        </div>
                    </div>
                </section>

                <!-- Authentication -->
                <section id="auth" class="glass-card p-6 rounded-2xl">
                    <h2 class="text-xl font-display font-bold text-slate-100 flex items-center gap-2 mb-4 border-b border-slate-800 pb-3">
                        <span class="text-emerald-400">🔑</span> Authentication
                    </h2>
                    <p class="text-xs sm:text-sm text-slate-300 leading-relaxed mb-4">
                        API Authorization requires passing your API Key. The gateway supports multiple authorization methods for maximum developer convenience:
                    </p>
                    <div class="space-y-2 font-mono text-xs mb-4">
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800 flex justify-between items-center">
                            <span class="text-emerald-400 font-bold">Header (Recommended)</span>
                            <code class="text-slate-300">Authorization: Bearer 70c9188c-e70e-4eb3-bd50-7d375d2a390c</code>
                        </div>
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800 flex justify-between items-center">
                            <span class="text-cyan-400 font-bold">JSON Body</span>
                            <code class="text-slate-300">"apiKey": "linux-lx0199222"</code>
                        </div>
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800 flex justify-between items-center">
                            <span class="text-purple-400 font-bold">URL Parameter</span>
                            <code class="text-slate-300">?apiKey=linux-lx0199222</code>
                        </div>
                    </div>
                </section>

                <!-- Sync Topup -->
                <section id="sync-topup" class="glass-card p-6 rounded-2xl glow-cyan">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
                        <h2 class="text-xl font-display font-bold text-slate-100 flex items-center gap-2">
                            <span class="text-cyan-400">🚀</span> Sync Topup — Instant Response
                        </h2>
                        <span class="px-2.5 py-1 rounded-md bg-emerald-500/10 text-emerald-400 font-mono text-xs font-bold border border-emerald-500/30">POST /topup-sync</span>
                    </div>
                    <p class="text-xs text-slate-400 mb-4">Direct response endpoint. Processes the voucher code(s) immediately and returns the exact transaction result.</p>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <!-- Request -->
                        <div>
                            <div class="flex items-center justify-between text-xs font-semibold text-slate-300 mb-2">
                                <span>📤 Request Payload (JSON)</span>
                                <span class="text-[10px] text-slate-500">Max 5 codes</span>
                            </div>
                            <pre class="p-4 bg-slate-950 rounded-xl border border-slate-800 text-xs text-emerald-400 overflow-x-auto"><code>{
  "orderid": "ORD-1001",
  "playerid": "228197025",
  "code": "BDMB-Q-S-15359391 2331-6265-6656-9336,BDMB-Q-S-15358262 5363-6431-5333-7468",
  "apiKey": "70c9188c-e70e-4eb3-bd50-7d375d2a390c"
}</code></pre>
                        </div>
                        <!-- Response -->
                        <div>
                            <div class="flex items-center justify-between text-xs font-semibold text-slate-300 mb-2">
                                <span>📥 Response (200 OK)</span>
                                <span class="text-[10px] text-emerald-400">UcBot Compatible</span>
                            </div>
                            <pre class="p-4 bg-slate-950 rounded-xl border border-slate-800 text-xs text-cyan-300 overflow-x-auto"><code>{
  "status": "success",
  "orderid": "ORD-1001",
  "nickname": "PlayerName",
  "username": "PlayerName",
  "region": "BD",
  "total": 2,
  "success": 2,
  "failed": 0,
  "batch": [
    {
      "uc": "BDMB-Q-S-15359391 2331-6265-6656-9336",
      "ok": true,
      "detail": "✅ Success",
      "trx_id": "UP-20260826-001"
    },
    {
      "uc": "BDMB-Q-S-15358262 5363-6431-5333-7468",
      "ok": true,
      "detail": "✅ Success",
      "trx_id": "UP-20260826-002"
    }
  ]
}</code></pre>
                        </div>
                    </div>
                </section>

                <!-- Async Topup -->
                <section id="async-topup" class="glass-card p-6 rounded-2xl">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
                        <h2 class="text-xl font-display font-bold text-slate-100 flex items-center gap-2">
                            <span class="text-purple-400">🔄</span> Async Topup — Webhook Callback
                        </h2>
                        <span class="px-2.5 py-1 rounded-md bg-purple-500/10 text-purple-400 font-mono text-xs font-bold border border-purple-500/30">POST /topup</span>
                    </div>
                    <p class="text-xs text-slate-400 mb-4">Returns HTTP 202 Accepted immediately. Processing happens in the background, and final results are POSTed to your webhook URL.</p>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <span class="text-xs font-semibold text-slate-300 block mb-2">📤 Request Payload</span>
                            <pre class="p-4 bg-slate-950 rounded-xl border border-slate-800 text-xs text-purple-300 overflow-x-auto"><code>{
  "orderid": "ORD-1002",
  "playerid": "228197025",
  "code": "BDMB-T-S-XXXXXX XXXX-XXXX-XXXX-XXXX",
  "url": "https://yoursite.com/api/webhook",
  "apiKey": "linux-lx0199222"
}</code></pre>
                        </div>
                        <div>
                            <span class="text-xs font-semibold text-slate-300 block mb-2">📥 Immediate Response (202 Accepted)</span>
                            <pre class="p-4 bg-slate-950 rounded-xl border border-slate-800 text-xs text-emerald-400 overflow-x-auto"><code>{
  "status": "accepted",
  "orderid": "ORD-1002"
}

/* Later POSTed to your webhook URL */
{
  "status": "success",
  "orderid": "ORD-1002",
  "nickname": "PlayerName",
  "batch": [...]
}</code></pre>
                        </div>
                    </div>
                </section>

                <!-- Prefix Mapping Table -->
                <section id="prefix-map" class="glass-card p-6 rounded-2xl">
                    <h2 class="text-xl font-display font-bold text-slate-100 flex items-center gap-2 mb-4 border-b border-slate-800 pb-3">
                        <span class="text-amber-400">🎯</span> Auto Package Detection Table
                    </h2>
                    <p class="text-xs text-slate-400 mb-4">The API inspects code prefixes (BDMB & UPBD series) to auto-detect denominations:</p>

                    <div class="overflow-x-auto rounded-xl border border-slate-800">
                        <table class="w-full text-xs text-left text-slate-300">
                            <thead class="bg-slate-900/80 text-emerald-400 font-mono uppercase text-[11px] border-b border-slate-800">
                                <tr>
                                    <th class="py-3 px-4">BDMB Series</th>
                                    <th class="py-3 px-4">UPBD Series</th>
                                    <th class="py-3 px-4">Product Name</th>
                                    <th class="py-3 px-4 text-center">Package ID</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-slate-800/60 font-mono">
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-T-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-Q-S</td><td class="py-2.5 px-4 font-sans text-slate-200">25 Diamond</td><td class="py-2.5 px-4 text-center text-amber-400">1</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-U-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-R-S</td><td class="py-2.5 px-4 font-sans text-slate-200">50 Diamond</td><td class="py-2.5 px-4 text-center text-amber-400">2</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-J-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-G-S</td><td class="py-2.5 px-4 font-sans text-slate-200">115 Diamond</td><td class="py-2.5 px-4 text-center text-amber-400">3</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-I-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-F-S</td><td class="py-2.5 px-4 font-sans text-slate-200">240 Diamond</td><td class="py-2.5 px-4 text-center text-amber-400">4</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-K-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-H-S</td><td class="py-2.5 px-4 font-sans text-slate-200">610 Diamond</td><td class="py-2.5 px-4 text-center text-amber-400">5</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-L-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-I-S</td><td class="py-2.5 px-4 font-sans text-slate-200">1240 Diamond</td><td class="py-2.5 px-4 text-center text-amber-400">6</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-M-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-J-S</td><td class="py-2.5 px-4 font-sans text-slate-200">2530 Diamond</td><td class="py-2.5 px-4 text-center text-amber-400">7</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-Q-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-N-S</td><td class="py-2.5 px-4 font-sans text-slate-200">Weekly Membership</td><td class="py-2.5 px-4 text-center text-amber-400">8</td></tr>
                                <tr class="hover:bg-slate-900/40"><td class="py-2.5 px-4 text-emerald-400 font-bold">BDMB-S-S</td><td class="py-2.5 px-4 text-cyan-400 font-bold">UPBD-P-S</td><td class="py-2.5 px-4 font-sans text-slate-200">Monthly Membership</td><td class="py-2.5 px-4 text-center text-amber-400">9</td></tr>
                            </tbody>
                        </table>
                    </div>
                </section>

                <!-- HTTP Response Codes -->
                <section id="status-codes" class="glass-card p-6 rounded-2xl">
                    <h2 class="text-xl font-display font-bold text-slate-100 flex items-center gap-2 mb-4 border-b border-slate-800 pb-3">
                        <span class="text-emerald-400">🚦</span> HTTP Status Codes
                    </h2>
                    <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800"><span class="text-emerald-400 font-mono font-bold">200 OK</span><p class="text-[11px] text-slate-400 mt-1">Successful order execution</p></div>
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800"><span class="text-purple-400 font-mono font-bold">202 Accepted</span><p class="text-[11px] text-slate-400 mt-1">Async order accepted for callback</p></div>
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800"><span class="text-amber-400 font-mono font-bold">400 Bad Request</span><p class="text-[11px] text-slate-400 mt-1">Missing required fields or >5 codes</p></div>
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800"><span class="text-red-400 font-mono font-bold">401 Unauthorized</span><p class="text-[11px] text-slate-400 mt-1">Invalid or missing API key</p></div>
                        <div class="p-3 bg-slate-900/80 rounded-xl border border-slate-800"><span class="text-red-400 font-mono font-bold">500 Server Error</span><p class="text-[11px] text-slate-400 mt-1">Internal server or scraper failure</p></div>
                    </div>
                </section>

            </main>
        </div>
    </div>

    <!-- Footer -->
    <footer class="border-t border-slate-900 py-8 text-center text-xs text-slate-500 bg-slate-950">
        <p>&copy; 2026 <span class="text-slate-300 font-semibold">LinuxUniPin v2</span>. Developed with FastAPI & Asyncio Concurrent Workers.</p>
    </footer>

    <script>
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(() => {
                alert('Copied to clipboard: ' + text);
            });
        }
    </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=HTML_CONTENT)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
