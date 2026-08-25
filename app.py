from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
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

    # Step 3: Preflight & CSRF
    preflight_url = "https://shop.garena.my/api/preflight"
    role_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; datadome={new_datadome}; session_key={session_key}"
    }
    preflight_res = scraper.post(preflight_url, headers=role_headers)
    set_cookie = preflight_res.headers.get('Set-Cookie', '')
    csrf_match = re.search(r'__csrf__=([^;]+)', set_cookie)
    new_csrf = csrf_match.group(1) if csrf_match else "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"

    # Step 4: Payment Init (UniPin URL আনা)
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
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": "https://shop.garena.my/",
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_1}; unipin_session={session_1}"
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
            "origin": "https://www.unipin.com",
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "referer": f"https://www.unipin.com/unibox/select_denom/{unique_id}?lg=en",
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_2}; unipin_session={session_2}"
        }
        payload3 = {"_token": meta_token, "denomination": DENOM_LIST[packageId]['payload']}
        res3 = scraper.post(denom_page_url, data=payload3, headers=headers3)

        c3 = scraper.cookies.get_dict()
        xsrf_3 = c3.get('__Host-XSRF-TOKEN', xsrf_2)
        session_3 = c3.get('unipin_session', session_2)

        # Step 4: সিরিয়াল ও পিন পার্স করা
        parts        = user_input.strip().split(" ")
        clean_serial = parts[0].replace("-", "")
        pin_parts    = parts[1].split("-")
        path_id      = get_path_id(user_input)

        # Step 5: ভাউচার সাবমিট (Final Direct POST)
        final_post_url = f"https://www.unipin.com/unibox/c/{unique_id}/{path_id}"
        headers6 = {
            "origin": "https://www.unipin.com",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.119 Mobile Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"https://www.unipin.com/unibox/c/{unique_id}/{path_id}?b=1",
            "cookie": f"region=BGD; unipin_session={session_3}; __Host-XSRF-TOKEN={xsrf_3}"
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

def process_single_code(args_tuple: tuple) -> tuple:
    """
    একটি একক কোডের জন্য Garena Session Init ও UniPin Redeem সম্পন্ন করে।
    Parallel execution-এর জন্য ব্যবহৃত হয়।
    """
    idx, code, uid, fallback_package_id = args_tuple
    code = code.strip()
    if not code:
        return idx, None, False, "N/A", "N/A"

    # কোড দেখে প্যাক নির্ধারণ (না পারলে রিকোয়েস্টের packageId)
    pkg = detect_package_id(code) or fallback_package_id

    # Garena সেশন ইনিট
    init_res = garena_payment_init(str(uid))

    if init_res["status"] == "error":
        batch_item = {
            "uc": code,
            "ok": False,
            "detail": f"❌ {init_res['message']}"
        }
        return idx, batch_item, False, "N/A", "N/A"

    nick = init_res.get("nickname", "N/A")
    reg  = init_res.get("region", "N/A")

    # ভাউচার রিডিম
    redeem_res = execute_redeem(init_res["url"], pkg, code)
    ok = redeem_res["status"] == "success"

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


def process_batch(uid: str, packageId: str, codes: list, orderid: str) -> dict:
    """
    একাধিক UniPin ভাউচার কোড প্রসেস করে batch রেজাল্ট রিটার্ন করে।
    একাধিক কোড থাকলে ThreadPoolExecutor দিয়ে প্যারালালে (একসাথে) দ্রুত রিডিম করা হয়।
    """
    valid_tasks = [(i, code, uid, packageId) for i, code in enumerate(codes) if code.strip()]

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
        # ১টি কোড থাকলে কোনো থ্রেড পুল ছাড়াই সরাসরি ফাস্ট প্রসেস (অতিরিক্ত ওভারহেড ছাড়া)
        idx, item, ok, nick, reg = process_single_code(valid_tasks[0])
        raw_results[0] = item
        if ok:
            success_count += 1
        else:
            fail_count += 1
        if nick != "N/A": nickname = nick
        if reg != "N/A":  region = reg
    else:
        # একাধিক কোড (২-৫টি) থাকলে ThreadPoolExecutor দিয়ে প্যারালালে প্রসেস করো (৫ গুণ ফাস্ট)
        max_workers = min(len(valid_tasks), 5)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            task_outputs = list(executor.map(process_single_code, valid_tasks))

        for idx, item, ok, nick, reg in task_outputs:
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
    html_content = """<!DOCTYPE html>
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
                    <span class="hidden sm:inline-block text-[10px] uppercase font-mono px-2 py-0.5 ml-2 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">v2.0 Live</span>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <span class="hidden sm:flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-mono text-emerald-400">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> 99.9% Uptime
                </span>
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
                Fastest UniPin Voucher API Gateway
            </div>
            <h1 class="text-3xl sm:text-5xl font-display font-extrabold text-slate-100 tracking-tight leading-tight">
                Free Fire TopUp <span class="text-gradient">API Documentation</span>
            </h1>
            <p class="text-slate-400 text-sm sm:text-base max-w-2xl mt-3 leading-relaxed">
                Automated, high-concurrency REST API for UniPin Bangladesh voucher redemptions. Supports parallel thread batch processing, auto package detection, and webhook callbacks.
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
                            <h3 class="font-bold text-sm text-slate-200">Parallel Execution</h3>
                            <p class="text-xs text-slate-400 mt-1">Multi-code batch orders execute simultaneously using ThreadPoolExecutor (~2.7s for 2-5 codes).</p>
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
        <p>&copy; 2026 <span class="text-slate-300 font-semibold">LinuxUniPin v2</span>. Developed with Flask & ThreadPoolExecutor.</p>
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
