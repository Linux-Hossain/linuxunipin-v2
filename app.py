from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import cloudscraper
from bs4 import BeautifulSoup
import re
import json
import os
import uuid
import threading
import requests as http_requests
from urllib.parse import urlencode

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
VALID_API_KEYS = {
    "linux-lx0199222",
    "70c9188c-e70e-4eb3-bd50-7d375d2a390c",
}
TRANSACTION_LOG  = "transaction.json"
FAILED_LOG       = "failed.json"
MAX_CODES_PER_ORDER = 5


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
    "9":  {"name": "Monthly Membership", "payload": '{"name":"Monthly Membership","amount":"800.0","amount_uc":"800.0","amount_up":800}'}
}

# ─── UniPin Code Prefix → Package ID Map ─────────────────────────────────────
# Real API log (10,704 lines, 4,048 CALL entries) থেকে বিশ্লেষণ করে তৈরি।
# Format: BDMB-Q-S-15359391 2331-6265-6656-9336
#          └──────┘  ← এই prefix দিয়ে product চেনা যায়
#
# BDMB Series (Bangladesh Mobile) | UPBD Series (UniPin Bangladesh)
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

    Returns packageId string (1-9) অথবা None যদি অজানা prefix হয়।
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


def check_api_key(data: dict):
    """
    রিকোয়েস্ট থেকে API Key বের করে যাচাই করে।
    Priority: Authorization Header → apiKey (body) → apiKey (query param)
    Returns: (is_valid: bool, error_response | None)
    """
    key = ""
    auth = request.headers.get("Authorization", "").strip()
    if auth:
        key = auth.replace("Bearer ", "").strip()
    elif data and data.get("apiKey"):
        key = str(data["apiKey"]).strip()
    else:
        key = request.args.get("apiKey", "").strip()

    if not key:
        return False, (jsonify({"status": "error", "message": "Missing API key."}), 401)
    if key not in VALID_API_KEYS:
        return False, (jsonify({"status": "error", "message": "Invalid API Key."}), 401)
    return True, None



# ─── Logging ──────────────────────────────────────────────────────────────────

def log_data(filename: str, data: dict):
    """JSON ফাইলে লগ এন্ট্রি যুক্ত করে"""
    try:
        logs = []
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    logs = json.load(f)
                except json.JSONDecodeError:
                    logs = []
        data["log_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logs.append(data)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Log Error: {e}")


# ─── Garena Payment Init ──────────────────────────────────────────────────────

def garena_payment_init(player_id: str) -> dict:
    """
    Garena শপে লগইন করে UniPin পেমেন্ট ইনিট URL সংগ্রহ করে।
    Returns: {"status": "success", "url": ..., "nickname": ..., "region": ...}
             or {"status": "error", "message": ...}
    """
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'android', 'desktop': False}
    )

    # Step 1: মূল পেজ থেকে mspid2 কুকি নাও
    scraper.get("https://shop.garena.my")
    mspid2 = scraper.cookies.get('mspid2', '')

    if not mspid2:
        return {"status": "error", "message": "mspid2 not found! Check VPN/IP."}

    # Step 2: Player ID দিয়ে লগইন
    login_url = "https://shop.garena.my/api/auth/player_id_login"
    login_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": "\"Android\"",
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7871.124 Mobile Safari/537.36",
        "sec-ch-ua": "\"Not;A=Brand\";v=\"8\", \"Chromium\";v=\"150\", \"Android WebView\";v=\"150\"",
        "Content-Type": "application/json",
        "sec-ch-ua-mobile": "?1",
        "Accept": "*/*",
        "Origin": "https://shop.garena.my",
        "X-Requested-With": "mark.via.gp",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://shop.garena.my/",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": f"source=mb; region=SG; language=en; mspid2={mspid2}; datadome=nlGy58ylgnGLA7pbxHdEpTXIsdw5R8RBCix0cQMSBVv0awQIhiqELM4qjar2WzXtzFVXS1xAWKnpGquK491kPw2FqLg30LzNkG7O1RYBHswcrUGw5ASGX8JZLjT9inpl; _fbp=fb.1.1787337260137.26816900912074180"
    }
    login_payload = {"app_id": 100067, "login_id": player_id}

    try:
        login_res = scraper.post(login_url, headers=login_headers, json=login_payload)
        login_data = login_res.json()
        login_nickname = login_data.get('nickname', '')
        login_region = login_data.get('region', '')

        if not login_nickname:
            return {"status": "error", "message": "Invalid Player ID or empty nickname"}
    except Exception:
        return {"status": "error", "message": "Login data could not be collected."}

    new_datadome = scraper.cookies.get('datadome', '')
    session_key = scraper.cookies.get('session_key', '')

    if not session_key:
        return {"status": "error", "message": "Session Key not found."}

    # Step 3: Role ভেরিফিকেশন
    role_url = "https://shop.garena.my/api/shop/apps/roles?app_id=100067&region=MY&language=en&source=mb"
    role_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
        "sec-ch-ua-mobile": "?1",
        "X-Requested-With": "mark.via.gp",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://shop.garena.my/?app=100067&channel=202953",
        "accept-encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; _fbp=fb.1.1774388514116.22736515472593712; __csrf__=zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7; datadome={new_datadome}; session_key={session_key}"
    }

    try:
        role_res = scraper.get(role_url, headers=role_headers)
        role_data = role_res.json()
        player_info = role_data.get("100067", [])[0]

        role_nickname = player_info.get("role", "")
        role_region = player_info.get("region", "")

        if role_nickname != login_nickname or role_region != login_region:
            return {"status": "error", "message": f"Verification Failed! Mismatch: Expected {login_nickname}, Found {role_nickname}"}
    except Exception:
        return {"status": "error", "message": "Roles not found or verification failed."}

    # Step 4: Preflight & CSRF
    preflight_url = "https://shop.garena.my/api/preflight"
    preflight_res = scraper.post(preflight_url, headers=role_headers)
    set_cookie = preflight_res.headers.get('Set-Cookie', '')
    csrf_match = re.search(r'__csrf__=([^;]+)', set_cookie)
    new_csrf = csrf_match.group(1) if csrf_match else "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"

    # Step 5: Payment Init (UniPin URL আনা)
    pay_init_url = "https://shop.garena.my/api/shop/pay/init?region=MY&language=en"
    pay_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "x-csrf-token": new_csrf,
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
        "Content-Type": "application/json",
        "sec-ch-ua-mobile": "?1",
        "Origin": "https://shop.garena.my",
        "X-Requested-With": "mark.via.gp",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://shop.garena.my/?app=100067&channel=202953",
        "accept-encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
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
        final_res = scraper.post(pay_init_url, headers=pay_headers, json=pay_payload)
        init_url = final_res.json().get('init', {}).get('url', '')
        if init_url:
            return {"status": "success", "url": init_url, "nickname": login_nickname, "region": login_region}
        return {"status": "error", "message": "Init URL not found in response"}
    except Exception:
        return {"status": "error", "message": "Failed to fetch payment init URL"}


# ─── UniPin Voucher Redeem ────────────────────────────────────────────────────

def execute_redeem(input_url: str, packageId: str, user_input: str) -> dict:
    """
    UniPin-এ ভাউচার সিরিয়াল ও পিন সাবমিট করে রিডিম করে।
    Returns: {"status": "success", "details": {...}}
             or {"status": "error", "message": ...}
    """
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'desktop': False})

    match = re.search(r'/unibox/d/([^?]+)', input_url)
    if not match:
        return {"status": "error", "message": "Invalid Unique ID in URL"}
    unique_id = match.group(1)

    try:
        # Step 1: UniPin session শুরু
        res1 = scraper.get(input_url, headers={
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "referer": "https://shop.garena.my/"
        })
        c1 = scraper.cookies.get_dict()
        xsrf_1 = c1.get('__Host-XSRF-TOKEN', '')
        session_1 = c1.get('unipin_session', '')

        # Step 2: Denomination সিলেকশন পেজ লোড
        denom_page_url = f"https://www.unipin.com/unibox/select_denom/{unique_id}?lg=en"
        headers2 = {
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "dnt": "1",
            "x-requested-with": "mark.via.gp",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "sec-fetch-user": "?1",
            "sec-fetch-dest": "document",
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "referer": "https://shop.garena.my/",
            "accept-encoding": "gzip, deflate",
            "accept-language": "en-US,en;q=0.9",
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_1}; unipin_session={session_1}",
            "priority": "u=0, i"
        }
        res2 = scraper.get(denom_page_url, headers=headers2)

        c2 = scraper.cookies.get_dict()
        xsrf_2 = c2.get('__Host-XSRF-TOKEN', xsrf_1)
        session_2 = c2.get('unipin_session', session_1)

        soup2 = BeautifulSoup(res2.text, 'html.parser')
        meta_tag = soup2.find('meta', {'name': 'csrf-token'})

        if not meta_tag:
            return {"status": "error", "message": "csrf-token meta tag not found!"}

        meta_token = meta_tag['content']

        # Step 3: Denomination সিলেক্ট করে POST
        headers3 = {
            "cache-control": "max-age=0",
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "origin": "https://www.unipin.com",
            "content-type": "application/x-www-form-urlencoded",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "x-requested-with": "mark.via.gp",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "navigate",
            "sec-fetch-user": "?1",
            "sec-fetch-dest": "document",
            "referer": f"https://www.unipin.com/unibox/select_denom/{unique_id}?lg=en",
            "accept-encoding": "gzip, deflate",
            "accept-language": "en-US,en;q=0.9",
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_2}; unipin_session={session_2}",
            "priority": "u=0, i"
        }
        payload3 = {"_token": meta_token, "denomination": DENOM_LIST[packageId]['payload']}
        res3 = scraper.post(denom_page_url, data=payload3, headers=headers3)

        c3 = scraper.cookies.get_dict()
        xsrf_3 = c3.get('__Host-XSRF-TOKEN', xsrf_2)
        session_3 = c3.get('unipin_session', session_2)

        # Step 4: ভাউচার পেজ লোড
        headers4 = {
            "cache-control": "max-age=0",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "x-requested-with": "mark.via.gp",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "navigate",
            "sec-fetch-user": "?1",
            "sec-fetch-dest": "document",
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "referer": f"https://www.unipin.com/unibox/select_denom/{unique_id}?lg=en",
            "accept-encoding": "gzip, deflate",
            "accept-language": "en-US,en;q=0.9",
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_3}; unipin_session={session_3}",
            "priority": "u=0, i"
        }
        res4 = scraper.get(input_url, headers=headers4)

        c4 = scraper.cookies.get_dict()
        xsrf_4 = c4.get('__Host-XSRF-TOKEN', xsrf_3)
        session_4 = c4.get('unipin_session', session_3)

        # Step 5: সিরিয়াল ও পিন পার্স করা
        parts        = user_input.strip().split(" ")
        clean_serial = parts[0].replace("-", "")
        pin_parts    = parts[1].split("-")
        # get_path_id() দিয়ে BDMB বা UPBD series অনুযায়ী সঠিক path_id নির্ধারণ
        path_id      = get_path_id(user_input)

        # Step 6: ভাউচার পেজ GET
        voucher_url = f"https://www.unipin.com/unibox/c/{unique_id}/{path_id}?b=1"
        headers5 = {
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "dnt": "1",
            "x-requested-with": "mark.via.gp",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "sec-fetch-user": "?1",
            "sec-fetch-dest": "document",
            "referer": f"https://www.unipin.com/unibox/d/{unique_id}?lg=en",
            "accept-encoding": "gzip, deflate",
            "accept-language": "en-US,en;q=0.9",
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_4}; unipin_session={session_4}; _tt_enable_cookie=1; _ttp=01KMPH66ZA1R8C2S27SPNJ6ANS_.tt.1; _scid=bAa4BzLCsUkwN-VwL81TU50bdIxsEyT6; _scid_r=bAa4BzLCsUkwN-VwL81TU50bdIxsEyT6; _sc_cspv=https%3A%2F%2Ftr.snapchat.com",
            "priority": "u=0, i"
        }
        res5 = scraper.get(voucher_url, headers=headers5)

        c5 = scraper.cookies.get_dict()
        xsrf_5 = c5.get('__Host-XSRF-TOKEN', xsrf_4)
        session_5 = c5.get('unipin_session', session_4)

        # Step 7: ভাউচার সাবমিট (Final POST)
        final_post_url = f"https://www.unipin.com/unibox/c/{unique_id}/{path_id}"
        headers6 = {
            "cache-control": "max-age=0",
            "origin": "https://www.unipin.com",
            "sec-ch-ua-platform": '"Android"',
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
            "upgrade-insecure-requests": "1",
            "sec-ch-ua-mobile": "?1",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "content-type": "application/x-www-form-urlencoded",
            "x-requested-with": "mark.via.gp",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "empty",
            "referer": f"https://www.unipin.com/unibox/c/{unique_id}/{path_id}?b=1",
            "accept-encoding": "gzip, deflate",
            "accept-language": "en-US,en;q=0.9",
            "cookie": f"region=BGD; unipin_session={session_5}; __Host-XSRF-TOKEN={xsrf_5}",
            "priority": "u=0, i"
        }
        final_payload = {
            "_token": meta_token,
            "serial": clean_serial,
            "pin_1": pin_parts[0],
            "pin_2": pin_parts[1],
            "pin_3": pin_parts[2],
            "pin_4": pin_parts[3]
        }

        final_res = scraper.post(final_post_url, data=urlencode(final_payload), headers=headers6)
        final_soup = BeautifulSoup(final_res.text, 'html.parser')

        # Step 8: রেজাল্ট পার্স
        if "Transaction successful" in final_res.text or final_soup.find(string=re.compile("Transaction successful")):
            def get_val(label_text):
                label = final_soup.find('div', class_='details-label', string=re.compile(label_text, re.I))
                if label:
                    val = label.find_next_sibling('div', class_='details-value')
                    return val.get_text(strip=True) if val else "N/A"
                return "N/A"

            trans_id = final_soup.find(id='trans_id')
            details = {
                "date": get_val('Transaction Date'),
                "trans_no": trans_id.get_text(strip=True) if trans_id else 'N/A',
                "reference": get_val('Reference'),
                "item": get_val('Item'),
                "amount": get_val('Transaction Amount')
            }
            return {"status": "success", "details": details}

        elif final_soup.find('div', class_='validationError'):
            err_div = final_soup.find('div', class_='alert alert-danger')
            return {"status": "error", "message": err_div.get_text(strip=True) if err_div else 'Invalid Serial'}

        elif "Consumed%20Voucher" in final_res.text or "Consumed Voucher" in final_res.text:
            return {"status": "error", "message": "Consumed Voucher (Already Used)"}

        else:
            msg_tag = final_soup.find('h1', class_='title-case-0')
            return {"status": "error", "message": msg_tag.get_text(strip=True) if msg_tag else 'Unknown Error'}

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Batch Processor ──────────────────────────────────────────────────────────

def process_batch(uid: str, packageId: str, codes: list, orderid: str) -> dict:
    """
    একাধিক UniPin ভাউচার কোড প্রসেস করে batch রেজাল্ট রিটার্ন করে।
    প্রতিটি কোডের জন্য আলাদাভাবে Garena সেশন ইনিট ও UniPin রিডিম করা হয়।
    """
    batch_results = []
    success_count = 0
    fail_count    = 0
    nickname      = "N/A"
    region        = "N/A"

    for i, code in enumerate(codes):
        code = code.strip()
        if not code:
            continue

        # প্রতিটি কোডের জন্য নতুন Garena সেশন ইনিট
        init_res = garena_payment_init(str(uid))

        if init_res["status"] == "error":
            batch_results.append({
                "uc": code,
                "ok": False,
                "detail": f"❌ {init_res['message']}"
            })
            fail_count += 1
            continue

        nickname = init_res.get("nickname", nickname)
        region   = init_res.get("region", region)

        # ভাউচার রিডিম
        redeem_res = execute_redeem(init_res["url"], packageId, code)
        ok = redeem_res["status"] == "success"

        if ok:
            detail = "✅ Success"
            success_count += 1
            # trx_id: UniPin transaction number (trans_no)
            trx_id = redeem_res.get("details", {}).get("trans_no", None)
            batch_item = {"uc": code, "ok": ok, "detail": detail}
            if trx_id and trx_id != "N/A":
                batch_item["trx_id"] = trx_id
            # Full UniPin receipt details
            if redeem_res.get("details"):
                batch_item["receipt"] = redeem_res["details"]
        else:
            msg = redeem_res.get("message", "Failed")
            detail = f"❌ {msg}"
            fail_count += 1
            batch_item = {"uc": code, "ok": ok, "detail": detail}

        batch_results.append(batch_item)

    # Overall Status নির্ধারণ
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

    # লগ সেভ
    log_entry = {
        "orderid": orderid,
        "uid": uid,
        "nickname": nickname,
        "region": region,
        "package": DENOM_LIST.get(packageId, {}).get("name", "Unknown"),
        "total_codes": total,
        "success": success_count,
        "failed": fail_count,
        "status": status
    }
    log_data(TRANSACTION_LOG if status != "failed" else FAILED_LOG, log_entry)

    return result


def send_callback(callback_url: str, payload: dict):
    """ব্যাকগ্রাউন্ডে Callback URL-এ POST পাঠায়"""
    try:
        http_requests.post(callback_url, json=payload, timeout=30)
    except Exception as e:
        print(f"[!] Callback Error to {callback_url}: {e}")


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route("/api/unipin", methods=["GET", "POST"])
@app.route("/topup-sync", methods=["POST"])
def unipin_api():
    """
    Sync TopUp Endpoint — তাৎক্ষণিক রেজাল্ট রিটার্ন করে।

    POST /api/unipin
    Body (JSON):
    {
        "orderid":   "ORD-001",          (optional)
        "uid":       "228197025",         (required)
        "packageId": "1",                 (required — 1-9)
        "code":      "CODE1,CODE2",       (required — কমা দিয়ে max 5টি)
        "apiKey":    "linux-lx0199222"   (required)
    }
    """
    data = {}
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict() or {}
    else:
        data = request.args.to_dict()

    # API Key যাচাই
    valid, err = check_api_key(data)
    if not valid:
        return err

    # Required ফিল্ড চেক
    uid      = data.get("uid") or data.get("playerid")
    raw_code = data.get("code", "")
    orderid  = data.get("orderid") or f"FLX-{str(uuid.uuid4())[:8].upper()}"

    if not uid or not raw_code:
        return jsonify({
            "status": "error",
            "message": "Missing required fields: uid, code"
        }), 400

    # Codes পার্স (কমা দিয়ে আলাদা, max 5)
    codes = [c.strip() for c in raw_code.split(",") if c.strip()]
    if len(codes) == 0:
        return jsonify({"status": "error", "message": "No valid codes provided."}), 400
    if len(codes) > MAX_CODES_PER_ORDER:
        return jsonify({
            "status": "error",
            "message": f"Max {MAX_CODES_PER_ORDER} codes per order. You sent {len(codes)}."
        }), 400

    # packageId: রিকোয়েস্ট থেকে নাও বা auto-detect করো কোড prefix দেখে
    package_id = data.get("packageId", "").strip()
    if not package_id:
        package_id = detect_package_id(codes[0])  # প্রথম কোড দেখে অটো-ডিটেক্ট
    if not package_id or package_id not in DENOM_LIST:
        return jsonify({
            "status": "error",
            "message": f"Cannot detect product from code prefix. Please provide packageId (1-9)."
        }), 400

    # Batch প্রসেস
    result = process_batch(uid, package_id, codes, orderid)
    return jsonify(result)


@app.route("/api/unipin/async", methods=["POST"])
@app.route("/topup", methods=["POST"])
def unipin_async():
    """
    Async TopUp Endpoint — তাৎক্ষণিক 202 Accepted রিটার্ন করে,
    প্রসেস শেষে Callback URL-এ POST পাঠায়।

    POST /api/unipin/async
    Body (JSON):
    {
        "orderid":   "ORD-001",
        "uid":       "228197025",
        "packageId": "1",
        "code":      "CODE1,CODE2",
        "url":       "https://yoursite.com/callback",   (required)
        "apiKey":    "linux-lx0199222"
    }
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}

    # API Key যাচাই
    valid, err = check_api_key(data)
    if not valid:
        return err

    # Required ফিল্ড চেক
    uid          = data.get("uid") or data.get("playerid")
    raw_code     = data.get("code", "")
    callback_url = data.get("url", "")
    orderid      = data.get("orderid") or f"FLX-{str(uuid.uuid4())[:8].upper()}"

    if not uid or not raw_code:
        return jsonify({"status": "error", "message": "Missing required fields: uid, code"}), 400

    if not callback_url:
        return jsonify({"status": "error", "message": "Missing required field: url (callback URL)"}), 400

    codes = [c.strip() for c in raw_code.split(",") if c.strip()]
    if len(codes) == 0:
        return jsonify({"status": "error", "message": "No valid codes provided."}), 400
    if len(codes) > MAX_CODES_PER_ORDER:
        return jsonify({
            "status": "error",
            "message": f"Max {MAX_CODES_PER_ORDER} codes per order."
        }), 400

    # packageId: রিকোয়েস্ট থেকে নাও বা auto-detect করো কোড prefix দেখে
    package_id = data.get("packageId", "").strip()
    if not package_id:
        package_id = detect_package_id(codes[0])
    if not package_id or package_id not in DENOM_LIST:
        return jsonify({
            "status": "error",
            "message": "Cannot detect product from code prefix. Please provide packageId (1-9)."
        }), 400

    # Background thread-এ প্রসেস শুরু করো
    def background_task():
        result = process_batch(uid, package_id, codes, orderid)
        send_callback(callback_url, result)

    thread = threading.Thread(target=background_task, daemon=True)
    thread.start()

    # তাৎক্ষণিক 202 রিটার্ন
    return jsonify({"status": "accepted", "orderid": orderid}), 202



@app.route("/api/history", methods=["GET"])
def api_history():
    """
    অর্ডার হিস্টোরি দেখায়।
    GET /api/history?apiKey=linux-lx0199222&limit=50
    """
    # GET request-এ দিয়ে apiKey যাচাই
    data = request.args.to_dict()
    valid, err = check_api_key(data)
    if not valid:
        return err

    limit    = min(int(request.args.get("limit", 50)), 200)
    log_type = request.args.get("type", "all")  # all, success, failed

    all_logs = []

    if log_type in ("all", "success") and os.path.exists(TRANSACTION_LOG):
        with open(TRANSACTION_LOG, "r", encoding="utf-8") as f:
            try:
                all_logs.extend(json.load(f))
            except Exception:
                pass

    if log_type in ("all", "failed") and os.path.exists(FAILED_LOG):
        with open(FAILED_LOG, "r", encoding="utf-8") as f:
            try:
                all_logs.extend(json.load(f))
            except Exception:
                pass

    all_logs.sort(key=lambda x: x.get("log_time", ""), reverse=True)
    all_logs = all_logs[:limit]

    return jsonify({
        "status": "success",
        "total": len(all_logs),
        "history": all_logs
    })



# ─── Home / Dashboard ─────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    packages_html = ""
    for pid, info in DENOM_LIST.items():
        packages_html += f"""
        <div class="glass-card rounded-xl p-4 flex justify-between items-center transition-all hover:border-blue-500/50">
            <div>
                <span class="text-blue-400 font-bold text-xs bg-blue-500/10 border border-blue-500/20 px-2.5 py-1 rounded-full">ID: {pid}</span>
                <h3 class="text-slate-200 font-semibold mt-3 text-sm">{info['name']}</h3>
            </div>
        </div>
        """

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Flexbase UniPin API Hub</title>
        <meta name="description" content="Automated Garena Free Fire UniPin voucher top-up gateway by Flexbase.">
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Plus Jakarta Sans', sans-serif; }
            .glass-card {
                background: rgba(30, 41, 59, 0.7);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(51, 65, 85, 0.6);
            }
            .glow-effect { box-shadow: 0 0 25px -5px rgba(59, 130, 246, 0.15); }
            .badge-get  { background: rgba(245,158,11,0.1); color:#fbbf24; border:1px solid rgba(245,158,11,0.3); }
            .badge-post { background: rgba(34,197,94,0.1);  color:#4ade80; border:1px solid rgba(34,197,94,0.3); }
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen p-6 md:p-10">
        <div class="max-w-4xl mx-auto">

            <!-- Header -->
            <header class="mb-10 text-center">
                <div class="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold uppercase tracking-wider mb-3">
                    <span class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
                    Flexbase Gateway Live
                </div>
                <h1 class="text-3xl md:text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 mb-2">
                    Flexbase API Hub
                </h1>
                <p class="text-slate-400 text-xs md:text-sm">Automated Garena Free Fire UniPin Top-up Gateway &mdash; v2.0</p>
            </header>

            <!-- Endpoints Overview -->
            <div class="glass-card rounded-2xl p-6 mb-6 glow-effect">
                <h2 class="text-lg font-bold text-blue-400 mb-4 border-b border-slate-800 pb-3">API Endpoints</h2>
                <div class="space-y-3">
                    <div class="flex items-center gap-3 bg-slate-900/60 rounded-xl px-4 py-3 border border-slate-800">
                        <span class="badge-post text-xs font-bold px-2.5 py-1 rounded-md">POST</span>
                        <code class="text-emerald-400 text-sm font-mono">/api/unipin</code>
                        <span class="text-slate-500 text-xs ml-auto">Sync Top-up — তাৎক্ষণিক রেজাল্ট</span>
                    </div>
                    <div class="flex items-center gap-3 bg-slate-900/60 rounded-xl px-4 py-3 border border-slate-800">
                        <span class="badge-post text-xs font-bold px-2.5 py-1 rounded-md">POST</span>
                        <code class="text-purple-400 text-sm font-mono">/api/unipin/async</code>
                        <span class="text-slate-500 text-xs ml-auto">Async Top-up — 202 + Callback</span>
                    </div>
                    <div class="flex items-center gap-3 bg-slate-900/60 rounded-xl px-4 py-3 border border-slate-800">
                        <span class="badge-get text-xs font-bold px-2.5 py-1 rounded-md">GET</span>
                        <code class="text-amber-400 text-sm font-mono">/api/status/&#123;token&#125;</code>
                        <span class="text-slate-500 text-xs ml-auto">Token ক্রেডিট ও মেয়াদ চেক</span>
                    </div>
                    <div class="flex items-center gap-3 bg-slate-900/60 rounded-xl px-4 py-3 border border-slate-800">
                        <span class="badge-get text-xs font-bold px-2.5 py-1 rounded-md">GET</span>
                        <code class="text-amber-400 text-sm font-mono">/api/history?token=&#123;token&#125;</code>
                        <span class="text-slate-500 text-xs ml-auto">অর্ডার হিস্টোরি দেখুন</span>
                    </div>
                </div>
            </div>

            <!-- Sync API Docs -->
            <div class="glass-card rounded-2xl p-6 mb-6 glow-effect">
                <h2 class="text-lg font-bold text-blue-400 mb-4 border-b border-slate-800 pb-3">POST /api/unipin — Sync Request</h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                    <!-- Request -->
                    <div>
                        <p class="text-xs text-slate-400 font-semibold mb-2">📤 Request Body (JSON)</p>
                        <pre class="text-xs text-emerald-400 font-mono bg-slate-950 p-3 rounded-xl border border-slate-800 overflow-x-auto">{
  "orderid":   "ORD-001",
  "uid":       "228197025",
  "packageId": "1",
  "code":      "CODE1,CODE2",
  "apiKey":    "your-uuid-token"
}</pre>
                        <p class="text-xs text-slate-500 mt-2">💡 <code>code</code>: কমা দিয়ে max ৫টি কোড<br>💡 <code>orderid</code>: optional (auto-generate হবে)<br>💡 <code>apiKey</code>-এর বদলে Header: <code>Authorization: TOKEN</code> ব্যবহার করুন</p>
                    </div>
                    <!-- Response -->
                    <div>
                        <p class="text-xs text-slate-400 font-semibold mb-2">📥 Success Response</p>
                        <pre class="text-xs text-emerald-400 font-mono bg-slate-950 p-3 rounded-xl border border-slate-800 overflow-x-auto">{
  "status":    "success",
  "orderid":   "ORD-001",
  "nickname":  "PlayerName",
  "region":    "BD",
  "success":   2,
  "failed":    0,
  "total":     2,
  "batch": [
    {"uc":"CODE1","ok":true,"detail":"✅ Success"},
    {"uc":"CODE2","ok":true,"detail":"✅ Success"}
  ]
}</pre>
                    </div>
                </div>
            </div>

            <!-- Async API Docs -->
            <div class="glass-card rounded-2xl p-6 mb-6">
                <h2 class="text-lg font-bold text-purple-400 mb-4 border-b border-slate-800 pb-3">POST /api/unipin/async — Async Request</h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                    <div>
                        <p class="text-xs text-slate-400 font-semibold mb-2">📤 Request Body</p>
                        <pre class="text-xs text-purple-400 font-mono bg-slate-950 p-3 rounded-xl border border-slate-800 overflow-x-auto">{
  "orderid":   "ORD-002",
  "uid":       "228197025",
  "packageId": "1",
  "code":      "CODE1,CODE2",
  "url":       "https://yoursite.com/cb",
  "apiKey":    "your-uuid-token"
}</pre>
                    </div>
                    <div>
                        <p class="text-xs text-slate-400 font-semibold mb-2">📥 Immediate Response (202)</p>
                        <pre class="text-xs text-purple-400 font-mono bg-slate-950 p-3 rounded-xl border border-slate-800 overflow-x-auto">{
  "status":  "accepted",
  "orderid": "ORD-002"
}
<span class="text-slate-500">-- প্রসেস শেষে আপনার url-এ --</span>
{
  "status":   "partial",
  "orderid":  "ORD-002",
  "success":  1,
  "failed":   1,
  "batch":    [...]
}</pre>
                    </div>
                </div>
            </div>

            <!-- Status Codes -->
            <div class="glass-card rounded-2xl p-6 mb-6">
                <h2 class="text-lg font-bold text-blue-400 mb-4 border-b border-slate-800 pb-3">HTTP Error Codes</h2>
                <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                    """ + "".join([f"""<div class="bg-slate-900/60 rounded-xl p-3 border border-slate-800">
                        <span class="text-red-400 font-bold font-mono text-sm">{code}</span>
                        <p class="text-slate-400 text-xs mt-1">{msg}</p>
                    </div>""" for code, msg in [
                        ("401", "Invalid/Missing Token"),
                        ("402", "Credits exhausted / expired"),
                        ("400", "Missing/invalid fields"),
                        ("429", "Rate limit (20/min)"),
                        ("500", "Internal server error"),
                        ("202", "Async order accepted"),
                    ]]) + """
                </div>
            </div>

            <!-- Packages -->
            <h2 class="text-xl font-bold mb-4 text-slate-200 border-b border-slate-800 pb-2">Available Package IDs</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 mb-10">
                """ + packages_html + """
            </div>

            <footer class="mt-6 text-center text-xs text-slate-500 border-t border-slate-900 pt-5">
                &copy; 2026 <span class="text-slate-400 font-semibold">Flexbase</span>. Powered by Flask &mdash; v2.0
            </footer>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_content)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # প্রথম রানে sample token তৈরি করো যদি tokens.json না থাকে
    if not os.path.exists(TOKENS_FILE):
        sample_token = str(uuid.uuid4())
        save_tokens({
            sample_token: {
                "name": "Flexbase Demo Shop",
                "account_status": "active",
                "max_limit": 1000,
                "limit_left": 1000,
                "valid_till": "2027-12-31 23:59:59",
                "used_this_month": 0,
                "deduct_on_fail": True
            }
        })
        print(f"\n✅ Sample API Token created: {sample_token}")
        print(f"   Check tokens.json for your token.\n")

    app.run(host="0.0.0.0", port=8000, debug=True)
