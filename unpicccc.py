from curl_cffi import requests
import json
import time
import re
import os
from urllib.parse import urlencode, quote, unquote
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

import itertools
import threading

USER_AGENT_MOBILE = "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

PROXY_POOL_SG = [
    "cghgkxjs-SG-rotate", "cghgkxjs-SG-1", "cghgkxjs-SG-2", "cghgkxjs-SG-3"
]
PROXY_CYCLE = itertools.cycle(PROXY_POOL_SG)
PROXY_LOCK = threading.Lock()

def create_garena_session():
    s = requests.Session(impersonate="chrome120")
    if os.getenv('WEBSHARE_ENABLED', 'true').lower() == 'true':
        host = os.getenv('WEBSHARE_HOST', 'p.webshare.io')
        port = os.getenv('WEBSHARE_PORT', '80')
        with PROXY_LOCK:
            user = next(PROXY_CYCLE)
        password = os.getenv('WEBSHARE_PASS', '9uvtmzg255yk')
        proxy = f'http://{user}:{password}@{host}:{port}'
        s.proxies = {'http': proxy, 'https': proxy}

    # 1. Visit homepage to establish mspid2 cookie
    init_headers = {
        "User-Agent": USER_AGENT_MOBILE,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }
    for _ in range(2):
        try:
            s.get("https://shop.garena.my", headers=init_headers)
            break
        except Exception:
            with PROXY_LOCK:
                user = next(PROXY_CYCLE)
            proxy = f'http://{user}:{password}@{host}:{port}'
            s.proxies = {'http': proxy, 'https': proxy}

    # 2. Fetch fresh datadome token from JS endpoint (datadome JS endpoint does NOT need proxy)
    try:
        js_s = requests.Session(impersonate="chrome120")
        js_res = js_s.post("https://datadome.garena.com/js/", data=urlencode({
            "ddk": "AE3F04AD3F0D3A462481A337485081",
            "Referer": "https://shop.garena.my/",
            "responseTarget": "https://shop.garena.my/",
            "eventUrl": "https://shop.garena.my/",
            "cid": ""
        }), headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://shop.garena.my",
            "Referer": "https://shop.garena.my/"
        })
        cookie_str = js_res.json().get("cookie", "")
        dd_match = re.search(r'datadome=([^;]+)', cookie_str)
        if dd_match:
            datadome = dd_match.group(1)
            s.cookies.set("datadome", datadome, domain=".garena.my")
            s.cookies.set("datadome", datadome, domain="shop.garena.my")
    except Exception:
        pass

    return s

def login_request(app_id, login_id, cookies=None, session=None):
    """
    Make a login request to Garena shop API
    """
    if session is None:
        session = create_garena_session()

    url = 'https://shop.garena.my/api/auth/player_id_login'

    mspid2 = session.cookies.get('mspid2', '')
    datadome = session.cookies.get('datadome', '')
    region = session.cookies.get('region', 'MY')

    headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "User-Agent": USER_AGENT_MOBILE,
        "sec-ch-ua": '"Chromium";v="120", "Not-A.Brand";v="24", "Android WebView";v="120"',
        "Content-Type": "application/json",
        "sec-ch-ua-mobile": "?1",
        "Accept": "*/*",
        "Origin": "https://shop.garena.my",
        "Referer": "https://shop.garena.my/?channel=202953",
        "Cookie": f"source=mb; region={region}; language=en; mspid2={mspid2}; datadome={datadome}"
    }

    data = {
        "app_id": app_id,
        "login_id": login_id
    }

    if cookies:
        if isinstance(cookies, str):
            cookie_dict = {}
            for item in cookies.split('; '):
                if '=' in item:
                    key, value = item.split('=', 1)
                    cookie_dict[key] = value
            cookies = cookie_dict
        for key, value in cookies.items():
            session.cookies.set(key, value)

    response = None
    for attempt in range(4):
        response = session.post(url, headers=headers, json=data)
        if response.status_code == 200 and ('open_id' in response.json() or 'nickname' in response.json()):
            break
        elif response.status_code == 403:
            res_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
            cap_url = res_data.get("url")
            if cap_url:
                session.get(cap_url, headers={"Referer": "https://shop.garena.my/"})
                new_dd = session.cookies.get('datadome', '')
                if new_dd:
                    session.cookies.set("datadome", new_dd, domain=".garena.my")
                    session.cookies.set("datadome", new_dd, domain="shop.garena.my")
                headers["Cookie"] = f"source=mb; region={region}; language=en; mspid2={mspid2}; datadome={new_dd}"
                retry_res = session.post(url, headers=headers, json=data)
                if retry_res.status_code == 200 and ('open_id' in retry_res.json() or 'nickname' in retry_res.json()):
                    response = retry_res
                    break
        session = create_garena_session()
        mspid2 = session.cookies.get('mspid2', '')
        datadome = session.cookies.get('datadome', '')
        headers["Cookie"] = f"source=mb; region={region}; language=en; mspid2={mspid2}; datadome={datadome}"

    return response, session

def proceed_to_payment(app_id=100067, channel_id=221179, region="MY", language="en", packed_role_id=0, session=None, csrf_token=None):
    """
    Proceed to payment after login - Initialize payment
    """
    if session is None:
        raise ValueError("Session object is required for payment request")

    new_datadome = session.cookies.get('datadome', '')
    session_key = session.cookies.get('session_key', '')
    session_id = session.cookies.get('mspid2', '')

    role_url = f"https://shop.garena.my/api/shop/apps/roles?app_id={app_id}&region={region}&language={language}&source=mb"
    role_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "User-Agent": USER_AGENT_MOBILE,
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua": '"Chromium";v="120", "Not-A.Brand";v="24", "Android WebView";v="120"',
        "sec-ch-ua-mobile": "?1",
        "Referer": "https://shop.garena.my/?app=100067&channel=202953",
        "Cookie": f"source=mb; region={region}; language={language}; mspid2={session_id}; datadome={new_datadome}; session_key={session_key}"
    }

    try:
        session.get(role_url, headers=role_headers)
    except Exception:
        pass

    preflight_url = "https://shop.garena.my/api/preflight"
    new_csrf = csrf_token or "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"
    try:
        preflight_res = session.post(preflight_url, headers=role_headers)
        set_cookie = preflight_res.headers.get('Set-Cookie', '')
        csrf_match = re.search(r'__csrf__=([^;]+)', set_cookie)
        if csrf_match:
            new_csrf = csrf_match.group(1)
    except Exception:
        pass

    url = f'https://shop.garena.my/api/shop/pay/init?region={region}&language={language}'
    pay_headers = {
        "Host": "shop.garena.my",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "x-csrf-token": new_csrf,
        "User-Agent": USER_AGENT_MOBILE,
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua": '"Chromium";v="120", "Not-A.Brand";v="24", "Android WebView";v="120"',
        "Content-Type": "application/json",
        "sec-ch-ua-mobile": "?1",
        "Origin": "https://shop.garena.my",
        "Referer": "https://shop.garena.my/?app=100067&channel=202953",
        "Cookie": f"source=mb; region={region}; language={language}; mspid2={session_id}; session_key={session_key}; datadome={new_datadome}; __csrf__={new_csrf}"
    }

    data = {
        "app_id": app_id,
        "packed_role_id": packed_role_id,
        "channel_id": channel_id,
        "service": "mb",
        "channel_data": {
            "need_return": True,
            "payment_channel": None
        },
        "revamp_experiment": {
            "session_id": session_id,
            "group": "treatment2",
            "service_version": "mshop_frontend_20260324",
            "source": "mb",
            "domain": "shop.garena.my"
        }
    }

    response = session.post(url, headers=pay_headers, json=data)
    if response.status_code == 403:
        res_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
        cap_url = res_data.get("url")
        if cap_url:
            session.get(cap_url, headers={"Referer": "https://shop.garena.my/"})
            response = session.post(url, headers=pay_headers, json=data)

    return response


def select_denomination_unipin(session, unipin_url, denomination_data):
    """
    Select a denomination on UniPin page

    Args:
        session: requests.Session object
        unipin_url: UniPin page URL (e.g., https://www.unipin.com/unibox/d/{token}?lg=en)
        denomination_data: Dictionary with denomination info (name, amount, amount_uc, amount_up)

    Returns:
        Response object from the submission
    """
    # IMPORTANT: First visit the /d/ page to establish session state
    # The server redirects /d/ to /select_denom/ automatically
    # We should use the CSRF token from this redirected response
    target_url = unipin_url.replace('/d/', '/select_denom/')
    try:
        page_response = session.get(target_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://shop.garena.my/'
        }, allow_redirects=True)
    except ValueError as e:
        if 'multiple cookies' in str(e).lower():
            page_response = session.get(target_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://shop.garena.my/'
            }, allow_redirects=True)
        else:
            raise

    form_url = page_response.url

    # Extract CSRF token
    csrf_match = re.search(
        r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', page_response.text)
    if not csrf_match:
        csrf_match = re.search(
            r'<input[^>]+name="_token"[^>]+value="([^"]+)"', page_response.text)

    csrf_token = csrf_match.group(1) if csrf_match else None

    if not csrf_token:
        print("⚠️  Warning: CSRF token not found!")

    # URL-encode the denomination JSON
    # From HAR: denomination=%7B%22name%22%3A%2225+Diamond%22%2C%22amount%22%3A%2220%22%2C%22amount_uc%22%3A%2220%22%2C%22amount_up%22%3A20%7D
    # Note: The JSON in HAR has no spaces after colons/commas
    # Use separators=(',', ':') to match HAR format exactly
    denom_json = json.dumps(denomination_data, separators=(',', ':'))
    # URL-encode the JSON string
    denom_encoded = quote(denom_json, safe='')

    print(f"Debug: CSRF Token: {csrf_token[:20] if csrf_token else 'None'}...")
    print(f"Debug: Denomination JSON: {denom_json}")
    print(f"Debug: Form URL: {form_url}")
    print(f"Debug: Session cookies: {dict(session.cookies)}")

    # Submit the form - denomination is already URL-encoded
    # We need to manually construct the form data string to avoid double-encoding
    # When using data=dict, requests.urlencode() will encode values again
    # Token should NOT be encoded (it's a plain string), only denomination is pre-encoded
    form_data_str = f"_token={csrf_token or ''}&denomination={denom_encoded}"

    print(
        f"Debug: Form data being sent: _token={csrf_token[:20] if csrf_token else 'None'}..., denomination={denom_encoded[:50]}...")
    print(f"Debug: POST data string: {form_data_str[:100]}...")

    # Submit the form - use data as string to avoid double-encoding
    # This ensures all cookies and session state are properly maintained
    # IMPORTANT: Referer should be the form_url (select_denom), not the original unipin_url
    response = session.post(
        form_url,
        data=form_data_str,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            # Use form_url (select_denom) as referer, not unipin_url
            'Referer': form_url,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://www.unipin.com',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Upgrade-Insecure-Requests': '1'
        },
        allow_redirects=True  # Let requests handle redirects automatically
    )

    # Debug: Check response
    print(f"Debug: Final response status: {response.status_code}")
    print(f"Debug: Final response URL: {response.url}")

    # Show redirect chain if any
    if response.history:
        print(f"Debug: Redirect chain ({len(response.history)} redirects):")
        for i, resp in enumerate(response.history):
            location = resp.headers.get('Location', 'N/A')
            print(f"  {i+1}. {resp.status_code} -> {location}")
            # Check if redirect response has any body content
            if resp.text:
                print(
                    f"      Response body (first 200 chars): {resp.text[:200]}")

    # Check response body for validation errors
    if response.text:
        # Look for common error patterns
        error_indicators = [
            r'<div[^>]*class="[^"]*alert[^"]*"[^>]*>([^<]+)</div>',
            r'<div[^>]*class="[^"]*error[^"]*"[^>]*>([^<]+)</div>',
            r'<p[^>]*class="[^"]*error[^"]*"[^>]*>([^<]+)</p>',
            r'validation.*error',
            r'csrf.*token',
            r'invalid.*token',
        ]
        for pattern in error_indicators:
            matches = re.findall(pattern, response.text, re.IGNORECASE)
            if matches:
                print(f"[!] Found error indicator: {matches[0][:150]}")

    # Check if we got redirected back to select_denom
    if '/select_denom/' in response.url:
        print("[!] Warning: Final URL is still select_denom page")
        # Check response content to see if it's actually the checkout page
        page_title = re.search(
            r'<title>([^<]+)</title>', response.text, re.IGNORECASE)
        if page_title:
            print(f"   Page title: {page_title.group(1)}")

        if 'checkout' in response.text.lower() or 'Select Payment Channel' in response.text or 'Physical Vouchers' in response.text:
            print(
                "[OK] Page content suggests we're on checkout page (URL might be misleading)")
        else:
            print("[ERROR] Page content confirms we're still on denomination selection")
            # Check if CSRF token might be the issue
            current_csrf = re.search(
                r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', response.text)
            if current_csrf:
                print(
                    f"   Current page CSRF token: {current_csrf.group(1)[:20]}...")
                if csrf_token and current_csrf.group(1) != csrf_token:
                    print("   [!] CSRF token changed! This might be the issue.")
            # Try to extract any error messages
            error_patterns = [
                r'<div[^>]*class="[^"]*error[^"]*"[^>]*>([^<]+)</div>',
                r'<p[^>]*class="[^"]*error[^"]*"[^>]*>([^<]+)</p>',
                r'alert[^>]*>([^<]+)',
            ]
            for pattern in error_patterns:
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                if matches:
                    print(f"   Found potential error: {matches[0][:100]}")

    return response


def get_payment_channel_links(checkout_url):
    """
    Extract payment channel links from checkout URL

    Args:
        checkout_url: UniPin checkout page URL (e.g., https://www.unipin.com/unibox/d/{token}?lg=en)

    Returns:
        Dictionary with payment channel links
    """
    # Extract token from URL
    token_match = re.search(r'/d/([^/?]+)', checkout_url)
    if not token_match:
        return {}

    token = token_match.group(1)

    return {
        'unipin_voucher': f'https://www.unipin.com/unibox/c/{token}/659?b=1',
        'up_gift_card': f'https://www.unipin.com/unibox/c/{token}/670?b=1'
    }


def parse_unipin_denominations(html_content):
    """
    Parse UniPin HTML page to extract denomination options

    Args:
        html_content: HTML content from UniPin page

    Returns:
        List of dictionaries containing denomination information
    """
    denominations = []

    # Pattern to match onclick="submit_form('{...}')"
    pattern = r"onclick=\"submit_form\('({[^']+})'\)\""
    matches = re.findall(pattern, html_content)

    for match in matches:
        try:
            # Replace HTML entities
            json_str = match.replace('&quot;', '"')
            # Parse the JSON
            data = json.loads(json_str)
            denominations.append({
                'name': data.get('name', ''),
                'amount': data.get('amount', ''),
                'amount_uc': data.get('amount_uc', ''),
                'amount_up': data.get('amount_up', '')
            })
        except json.JSONDecodeError as e:
            continue

    return denominations


DENOM_LIST = {
    "1": {"name": "25 Diamond", "payload": '{"name":"25 Diamond","amount":"20.0","amount_uc":"20.0","amount_up":20}'},
    "2": {"name": "50 Diamond", "payload": '{"name":"50 Diamond","amount":"36.0","amount_uc":"36.0","amount_up":36}'},
    "3": {"name": "115 Diamond", "payload": '{"name":"115 Diamond","amount":"80.0","amount_uc":"80.0","amount_up":80}'},
    "4": {"name": "240 Diamond", "payload": '{"name":"240 Diamond","amount":"160.0","amount_uc":"160.0","amount_up":160}'},
    "5": {"name": "610 Diamond", "payload": '{"name":"610 Diamond","amount":"405.0","amount_uc":"405.0","amount_up":405}'},
    "6": {"name": "1240 Diamond", "payload": '{"name":"1240 Diamond","amount":"810.0","amount_uc":"810.0","amount_up":810}'},
    "7": {"name": "2530 Diamond", "payload": '{"name":"2530 Diamond","amount":"1625.0","amount_uc":"1625.0","amount_up":1625}'},
    "8": {"name": "Weekly Membership", "payload": '{"name":"Weekly Membership","amount":"161.0","amount_uc":"161.0","amount_up":161}'},
    "9": {"name": "Monthly Membership", "payload": '{"name":"Monthly Membership","amount":"800.0","amount_uc":"800.0","amount_up":800}'}
}

INDEX_TO_PAYLOAD = {
    1: {"name": "25 Diamond", "amount": "20.0", "amount_uc": "20.0", "amount_up": 20},
    2: {"name": "50 Diamond", "amount": "36.0", "amount_uc": "36.0", "amount_up": 36},
    3: {"name": "115 Diamond", "amount": "80.0", "amount_uc": "80.0", "amount_up": 80},
    4: {"name": "240 Diamond", "amount": "160.0", "amount_uc": "160.0", "amount_up": 160},
    5: {"name": "610 Diamond", "amount": "405.0", "amount_uc": "405.0", "amount_up": 405},
    6: {"name": "1240 Diamond", "amount": "810.0", "amount_uc": "810.0", "amount_up": 810},
    7: {"name": "2530 Diamond", "amount": "1625.0", "amount_uc": "1625.0", "amount_up": 1625},
    8: {"name": "Weekly Membership", "amount": "161.0", "amount_uc": "161.0", "amount_up": 161},
    9: {"name": "Monthly Membership", "amount": "800.0", "amount_uc": "800.0", "amount_up": 800},
}

PREFIX_MAP = {
    "BDMB-T-S": "1", "BDMB-U-S": "2", "BDMB-J-S": "3", "BDMB-I-S": "4",
    "BDMB-K-S": "5", "BDMB-L-S": "6", "BDMB-M-S": "7", "BDMB-Q-S": "8", "BDMB-S-S": "9",
    "UPBD-Q-S": "1", "UPBD-R-S": "2", "UPBD-G-S": "3", "UPBD-F-S": "4",
    "UPBD-H-S": "5", "UPBD-I-S": "6", "UPBD-J-S": "7", "UPBD-N-S": "8", "UPBD-P-S": "9",
}

def channel_from_voucher(voucher_code: str | None) -> str:
    if not voucher_code or not isinstance(voucher_code, str):
        return "1"
    raw = voucher_code.strip().upper().replace("-", "").replace(" ", "")
    if raw.startswith("UPBD"):
        return "2"
    return "1"

def auto_detect_denom_index(voucher_code: str | None) -> int | None:
    if not voucher_code or not isinstance(voucher_code, str):
        return None
    raw = voucher_code.strip().upper()
    first_part = raw.split()[0] if raw.split() else raw
    segments = first_part.split("-")
    if len(segments) >= 3:
        prefix = "-".join(segments[:3])
        mapped = PREFIX_MAP.get(prefix)
        if mapped:
            return int(mapped)
    return None

ITEM_TO_INDEX = {
    "25": 1, "50": 2, "115": 3, "240": 4, "610": 5,
    "1240": 6, "2530": 7,
    "weekly": 8, "monthly": 9,
}

ITEM_DISPLAY = {
    "25": "25 Diamond", "50": "50 Diamond", "115": "115 Diamond",
    "240": "240 Diamond", "610": "610 Diamond", "1240": "1240 Diamond",
    "2530": "2530 Diamond", "weekly": "Weekly Membership", "monthly": "Monthly Membership",
}


def make_error_result(uid, unipin_code, error_type, error_message, url="", nickname="", item=""):
    return {
        "UID": uid or "",
        "NickName": nickname or "",
        "UnipinCode": unipin_code or "",
        "Item": item or "",
        "Transaction Date": "",
        "Date": "",
        "Merchant": "",
        "Transaction NO": "",
        "Reference": "",
        "Transaction Amount": "",
        "Status": "FAILED",
        "Error": error_type,
        "Error Message": error_message,
        "URL": url or "",
    }


def parse_unipin_voucher_form_error(html):
    if not html:
        return None
    for pattern, msg in [
        (r"Invalid\s+Serial", "Invalid Serial"),
        (r"Invalid\s+PIN", "Invalid PIN"),
        (r"Serial\s+already\s+used", "Serial already used"),
        (r"Invalid\s+voucher", "Invalid voucher"),
    ]:
        if re.search(pattern, html, re.IGNORECASE):
            return msg
    return None


def parse_unipin_result_page(html, url, login_id, voucher_code, nickname="", item_name=""):
    if "/unibox/error/" in url:
        err_match = re.search(r"/unibox/error/([^/?]+)", url)
        err_code = err_match.group(1) if err_match else "Unknown"
        try:
            err_code_decoded = unquote(err_code)
        except Exception:
            err_code_decoded = err_code
        err_lower = err_code_decoded.lower()
        if "consumed" in err_lower or "used" in err_lower:
            error_message_detail = "This voucher has already been used/consumed."
        elif "invalid" in err_lower:
            error_message_detail = "This voucher code is invalid."
        elif "expired" in err_lower:
            error_message_detail = "This voucher has expired."
        else:
            error_message_detail = f"Error type: {err_code_decoded}"
        error_result = make_error_result(
            login_id, voucher_code, err_code_decoded, error_message_detail, url, nickname, item_name
        )
        return error_result, None
    if "/unibox/result/" not in url:
        return None, None
    if html and (
        "Request Expired" in html
        or "Please try again to fill information within 30 seconds" in html
        or (re.search(r"EXPIRED", html, re.I) and re.search(r"30\s*seconds", html, re.I))
    ):
        error_result = make_error_result(
            login_id,
            voucher_code,
            "Request Expired",
            "The result link has expired. Please complete the transaction again within 30 seconds.",
            url,
            nickname,
            item_name,
        )
        return error_result, None
    result_data = {}
    for pattern in [
        r"var\s+pResult\s*=\s*(\{[^}]+\})",
        r"pResult\s*=\s*(\{[^}]+\})",
    ]:
        presult_match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if presult_match:
            try:
                json_str = presult_match.group(1)
                json_str = json_str.replace("'", '"')
                json_str = re.sub(r"(\w+)\s*:", r'"\1":', json_str)
                result_data = json.loads(json_str)
                break
            except (json.JSONDecodeError, Exception):
                pass
    if not result_data:
        for name, pat in [
            ("status", r'status\s*:\s*"([^"]+)"'),
            ("amount", r'amount\s*:\s*"([^"]+)"'),
            ("trxNo", r'trxNo\s*:\s*"([^"]+)"'),
            ("reference", r'reference\s*:\s*"([^"]+)"'),
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                result_data[name] = m.group(1)
    details_rows = re.findall(
        r'<div class="details-row">\s*<div class="details-label">\s*(.*?)\s*</div>\s*<div class="details-value"[^>]*>\s*(.*?)\s*</div>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not details_rows:
        details_rows = re.findall(
            r'class="[^"]*details-label[^"]*">\s*(.*?)\s*</div>\s*.*?class="[^"]*details-value[^"]*"[^>]*>\s*(.*?)\s*</div>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
    for label, value in details_rows:
        value_clean = re.sub(r"<[^>]+>", "", value).strip()
        value_clean = " ".join(value_clean.split())
        label_clean = label.strip().rstrip(":")
        if value_clean and label_clean:
            result_data[label_clean] = value_clean
    amount_div = re.search(
        r'<div class="checkout-amount">\s*(.*?)\s*</div>', html, re.IGNORECASE | re.DOTALL
    )
    if amount_div:
        amount_value = re.sub(r"<[^>]+>", "", amount_div.group(1)).strip()
        amount_value = " ".join(amount_value.split())
        if amount_value:
            result_data["Amount"] = amount_value
    date_val = result_data.get("Transaction Date", result_data.get("date", ""))
    item_val = result_data.get(
        "Item", result_data.get("item", "")) or item_name
    trx_no = (
        result_data.get("Transaction No.",
                        result_data.get("Transaction No", ""))
        or result_data.get("trxNo", result_data.get("Transaction NO", ""))
    )
    ref_val = result_data.get("Reference", result_data.get("reference", ""))
    amount_val = result_data.get(
        "Transaction Amount", result_data.get(
            "Amount", result_data.get("amount", ""))
    )
    formatted = {
        "UID": login_id,
        "NickName": nickname or "",
        "UnipinCode": voucher_code,
        "Item": item_val,
        "Transaction Date": date_val,
        "Date": date_val,
        "Merchant": result_data.get("Merchant", ""),
        "Transaction NO": trx_no,
        "Reference": ref_val,
        "Transaction Amount": amount_val,
        "Status": result_data.get("status", "SUCCESS") if result_data.get("status") else "SUCCESS",
        "URL": url,
    }
    return formatted, None


def channel_from_voucher(voucher_code: str | None) -> str:
    if not voucher_code or not isinstance(voucher_code, str):
        return "1"
    raw = voucher_code.strip().upper().replace("-", "").replace(" ", "")
    if raw.startswith("UPBD"):
        return "2"
    return "1"


# Same default cookies string that was hard-coded in `unpicccc copy.py`
DEFAULT_COOKIES = (
    "source=pc; region=MY; language=en; "
    "mspid2=c57ea0d0a87ffa03f9bc05e4bc148670; "
    "_fbp=fb.1.1769352799663.668363073435648750; "
    "_ga=GA1.1.687392890.1769352800; "
    "__csrf__=et8SMlggLbcmHoRPjVQBBykfxVow5YEY; "
    "session_key=o86mdt96qj7udch917bwnywz33co1e3a; "
    "datadome=V5XDhOAkuEW3LQVrN0LP~v_PzjZjC0kg0flsZWa2o16Kpyu0hLI4MUkxtnFvMTRNjkjRIivcW6cIksJe8semac5PmcDnpCBEK8iwzMo_boGJRFPX8Y4ofO_xZ1sDoEFW; "
    "_ga_9F1KGGRJHY=GS2.1.s1769352799$o1$g1$t1769353580$j41$l0$h0"
)


def run_unipin_flow(
    login_id: str,
    app_id: int = 100067,
    channel_id: int = 221179,
    denomination_index: int | None = None,
    cookies: str | dict | None = None,
    voucher_code: str | None = None,
):
    """
    Programmatic version of the main flow, suitable for API use.

    Returns a dict shaped like unipin.py:
      {"success": bool, "result": {...}}
    """
    session = requests.Session()

    # 1) Login (optionally with cookies like the old script)
    effective_cookies = cookies if cookies is not None else DEFAULT_COOKIES
    login_resp, session = login_request(
        app_id, login_id, cookies=effective_cookies, session=session)
    try:
        login_data = login_resp.json()
    except Exception:
        login_data = {}

    # Try to extract nickname from login response (similar to unipin.py)
    user_nickname = ""
    if isinstance(login_data, dict):
        sources = [login_data]
        if isinstance(login_data.get("data"), dict):
            sources.append(login_data["data"])
        for src in sources:
            for key in ("nickname", "nick_name", "display_name", "name", "user_name"):
                val = (src.get(key) or "").strip()
                if val:
                    user_nickname = val
                    break
            if user_nickname:
                break

    if login_resp.status_code != 200 or "open_id" not in login_data:
        return {
            "success": False,
            "result": make_error_result(
                uid=login_id,
                unipin_code=voucher_code,
                error_type="Login Failed",
                error_message="Player ID login failed after multiple retries (Invalid UID or Region Mismatch)",
                nickname=user_nickname,
            ),
        }

    # 2) Init payment
    pay_resp = proceed_to_payment(
        app_id, channel_id=channel_id, session=session)
    try:
        pay_data = pay_resp.json()
    except Exception:
        pay_data = {}

    if (
        pay_resp.status_code != 200
        or pay_data.get("result") != "success"
        or "init" not in pay_data
        or "url" not in pay_data["init"]
    ):
        return {
            "success": False,
            "result": make_error_result(
                uid=login_id,
                unipin_code=voucher_code,
                error_type="Payment Init Failed",
                error_message="Payment init failed or UniPin URL missing",
                nickname=user_nickname,
            ),
        }

    unipin_url = pay_data["init"]["url"]

    # 3) Fetch UniPin denominations
    unipin_session = requests.Session()
    up_resp = unipin_session.get(
        unipin_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://shop.garena.my/",
        },
    )

    if up_resp.status_code != 200:
        return {
            "success": False,
            "result": make_error_result(
                uid=login_id,
                unipin_code=voucher_code,
                error_type="Fetch UniPin Failed",
                error_message="Failed to fetch UniPin page",
                nickname=user_nickname,
            ),
        }

    # Auto-detect denomination_index from voucher_code if not specified
    if denomination_index is None and voucher_code:
        denomination_index = auto_detect_denom_index(voucher_code)

    if denomination_index and denomination_index in INDEX_TO_PAYLOAD:
        selected = INDEX_TO_PAYLOAD[denomination_index]
    else:
        denoms = parse_unipin_denominations(up_resp.text)
        if not denoms or not (1 <= (denomination_index or 0) <= len(denoms)):
            return {
                "success": False,
                "result": make_error_result(
                    uid=login_id,
                    unipin_code=voucher_code,
                    error_type="Invalid Denomination",
                    error_message=f"Invalid denomination_index: {denomination_index}",
                    nickname=user_nickname,
                ),
            }
        selected = denoms[denomination_index - 1]

    # 4) Submit denomination
    submit_resp = select_denomination_unipin(
        unipin_session, unipin_url, selected)
    if submit_resp.status_code != 200:
        return {
            "success": False,
            "result": make_error_result(
                uid=login_id,
                unipin_code=voucher_code,
                error_type="Denomination Submit Failed",
                error_message="Denomination submit failed",
                url=submit_resp.url,
                nickname=user_nickname,
                item=selected.get("name", ""),
            ),
        }

    # 5) From final URL, get payment channel links
    channel_links = get_payment_channel_links(submit_resp.url)
    if not channel_links:
        return {
            "success": False,
            "result": make_error_result(
                uid=login_id,
                unipin_code=voucher_code,
                error_type="Payment Links Failed",
                error_message="Could not derive payment channel links",
                url=submit_resp.url,
                nickname=user_nickname,
                item=selected.get("name", ""),
            ),
        }

    # If no voucher_code provided, just return links (prep step)
    if not voucher_code or not voucher_code.strip():
        return {
            "success": True,
            "result": {
                "login_id": login_id,
                "unipin_url": unipin_url,
                "selected_denomination": selected,
                "channel_links": channel_links,
            },
        }

    # 6) Submit voucher on the appropriate channel and parse result like unipin.py
    ch_choice = channel_from_voucher(voucher_code)
    target_url = (
        channel_links.get("up_gift_card")
        if ch_choice == "2"
        else channel_links.get("unipin_voucher")
    )
    if not target_url:
        return {
            "success": False,
            "result": make_error_result(
                login_id,
                voucher_code,
                "Error",
                "Payment channel URL not found",
                submit_resp.url,
                "",
                selected.get("name", ""),
            ),
        }

    try:
        # Open voucher page
        v_resp = unipin_session.get(
            target_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": submit_resp.url,
            },
            allow_redirects=True,
        )
        html = v_resp.text

        # Extract CSRF token
        csrf_match = re.search(
            r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', html
        )
        if not csrf_match:
            csrf_match = re.search(
                r'<input[^>]+name="_token"[^>]+value="([^"]+)"', html
            )
        csrf_token = csrf_match.group(1) if csrf_match else ""

        # Form action
        form_action_match = re.search(
            r'<form[^>]+action="([^"]+)"', html, re.IGNORECASE
        )
        form_action = form_action_match.group(
            1) if form_action_match else v_resp.url
        if form_action.startswith("/"):
            from urllib.parse import urlparse

            parsed = urlparse(v_resp.url)
            form_action = f"{parsed.scheme}://{parsed.netloc}{form_action}"
        if "?" in form_action:
            form_action = form_action.split("?", 1)[0]

        # Parse voucher code: "SERIAL PIN"
        parts = voucher_code.split(None, 1)
        serial_part = (parts[0] if parts else "").replace(
            "-", "").replace(" ", "")
        pin_part = parts[1] if len(parts) > 1 else ""
        pin_segments = re.split(r"[- ]+", pin_part) if pin_part else []

        # Build form data
        form_data = {"_token": csrf_token}

        # Serial field
        if serial_part:
            serial_input_match = re.search(
                r'name="([^"]*serial[^"]*)"', html, re.IGNORECASE
            )
            serial_name = serial_input_match.group(
                1) if serial_input_match else "serial"
            form_data[serial_name] = serial_part

        # PIN fields pin_1..pin_4
        if pin_segments:
            pin_fields = re.findall(r'name="(pin_\d+)"', html, re.IGNORECASE)
            if not pin_fields:
                pin_fields = [f"pin_{i}" for i in range(1, 5)]
            pin_fields_sorted = sorted(set(pin_fields))
            for i, name in enumerate(pin_fields_sorted):
                if i < len(pin_segments):
                    form_data[name] = pin_segments[i]

        # Submit voucher
        voucher_resp = unipin_session.post(
            form_action,
            data=form_data,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": v_resp.url,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.unipin.com",
            },
            allow_redirects=True,
        )

        result_html = voucher_resp.text
        result_url = voucher_resp.url

        formatted_result, _ = parse_unipin_result_page(
            result_html,
            result_url,
            login_id,
            voucher_code,
            user_nickname,
            selected.get("name", ""),
        )

        if formatted_result is None:
            form_err = parse_unipin_voucher_form_error(result_html)
            if form_err:
                return {
                    "success": False,
                    "result": make_error_result(
                        login_id,
                        voucher_code,
                        "Voucher Error",
                        form_err,
                        result_url,
                        user_nickname,
                        selected.get("name", ""),
                    ),
                }
            # Fallback generic error
            return {
                "success": False,
                "result": make_error_result(
                    login_id,
                    voucher_code,
                    "Error",
                    "Unable to parse voucher result",
                    result_url,
                    user_nickname,
                    selected.get("name", ""),
                ),
            }

        if formatted_result.get("Status") == "FAILED":
            return {"success": False, "result": formatted_result}
        return {"success": True, "result": formatted_result}

    except Exception as e:
        return {
            "success": False,
            "result": make_error_result(
                login_id,
                voucher_code or "",
                "Error",
                str(e),
                target_url,
                user_nickname,
                selected.get("name", ""),
            ),
        }


def process_multi_vouchers(uid: str, voucher_codes_raw: str, cookies: str | None = None):
    codes = [c.strip() for c in re.split(r'[\r\n,]+', voucher_codes_raw) if c.strip()]
    if not codes:
        return {"success": False, "error": "No valid voucher codes provided"}

    if len(codes) == 1:
        single_res = run_unipin_flow(login_id=uid.strip(), voucher_code=codes[0], cookies=cookies)
        return single_res

    results = []
    with ThreadPoolExecutor(max_workers=min(10, len(codes))) as executor:
        future_to_code = {
            executor.submit(
                run_unipin_flow,
                login_id=uid.strip(),
                voucher_code=code,
                cookies=cookies
            ): code for code in codes
        }
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                res = future.result()
                res_body = res.get("result") or {}
                results.append(res_body)
            except Exception as e:
                results.append(make_error_result(uid, code, "Error", str(e)))

    success_count = sum(1 for r in results if r.get("Status") == "SUCCESS")
    failed_count = len(results) - success_count

    return {
        "success": success_count > 0 or len(results) > 0,
        "total_codes": len(codes),
        "successful_codes": success_count,
        "failed_codes": failed_count,
        "results": results
    }


API_KEY_FILE = os.path.join(os.path.dirname(__file__), "api_keys.json")
API_KEY_REQUIRED = os.getenv("API_KEY_REQUIRED", "true").lower() == "true"
RATE_LIMIT_STORE = {}  # {api_key: [timestamps]}
RATE_LIMIT_LOCK = threading.Lock()
LAST_KEYS_MTIME = 0
CACHED_API_KEYS = {}

def load_api_keys() -> dict:
    global LAST_KEYS_MTIME, CACHED_API_KEYS
    try:
        if os.path.exists(API_KEY_FILE):
            mtime = os.path.getmtime(API_KEY_FILE)
            if mtime != LAST_KEYS_MTIME:
                with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                    CACHED_API_KEYS = json.load(f)
                LAST_KEYS_MTIME = mtime
    except Exception:
        pass

    if not CACHED_API_KEYS:
        CACHED_API_KEYS = {
            "demo_key_123": {"name": "Demo Client", "rate_limit": 60, "time_window_seconds": 60, "expires_at": None, "enabled": True},
            "ucbot_secret_token_99": {"name": "UcBot Reseller", "rate_limit": 120, "time_window_seconds": 60, "expires_at": "2030-12-31T23:59:59", "enabled": True},
        }
    return CACHED_API_KEYS

from datetime import datetime

def check_api_key_and_rate_limit(api_key: str | None) -> tuple[bool, str, int]:
    if not API_KEY_REQUIRED:
        return True, "", 200

    if not api_key:
        return False, "API key required. Provide via Authorization header, ?api_key=, or json body.", 401

    all_keys = load_api_keys()
    key_info = all_keys.get(api_key)
    if not key_info or not key_info.get("enabled", True):
        return False, "Invalid or disabled API key.", 403

    # Check key expiration date if configured
    expires_at = key_info.get("expires_at")
    if expires_at:
        try:
            if isinstance(expires_at, str):
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                exp_ts = exp_dt.timestamp()
            else:
                exp_ts = float(expires_at)
            
            if time.time() > exp_ts:
                return False, f"API key has expired on {expires_at}.", 403
        except Exception:
            pass

    limit = int(key_info.get("rate_limit") or key_info.get("rate_limit_per_min") or 60)
    window = int(key_info.get("time_window_seconds") or 60)
    now = time.time()
    cutoff = now - float(window)

    with RATE_LIMIT_LOCK:
        timestamps = RATE_LIMIT_STORE.get(api_key, [])
        valid_ts = [t for t in timestamps if t > cutoff]
        if len(valid_ts) >= limit:
            RATE_LIMIT_STORE[api_key] = valid_ts
            return False, f"Rate limit exceeded ({limit} requests per {window}s). Please try again later.", 429

        valid_ts.append(now)
        RATE_LIMIT_STORE[api_key] = valid_ts

    return True, "", 200


def get_key_status_info(api_key: str | None) -> dict:
    if not api_key:
        return {"status": "error", "message": "API key required"}
    
    all_keys = load_api_keys()
    key_info = all_keys.get(api_key)
    if not key_info or not key_info.get("enabled", True):
        return {"status": "error", "message": "Invalid or disabled API key"}

    limit = int(key_info.get("rate_limit") or key_info.get("rate_limit_per_min") or 60)
    window = int(key_info.get("time_window_seconds") or 60)
    now = time.time()
    cutoff = now - float(window)

    with RATE_LIMIT_LOCK:
        timestamps = RATE_LIMIT_STORE.get(api_key, [])
        valid_ts = [t for t in timestamps if t > cutoff]
        used = len(valid_ts)

    remaining = max(0, limit - used)
    expires_at = key_info.get("expires_at")

    return {
        "status": "success",
        "name": key_info.get("name", "Client"),
        "credits": 99999,
        "balance": 99999,
        "rate_limit": limit,
        "time_window_seconds": window,
        "used_requests": used,
        "remaining_requests": remaining,
        "expires_at": expires_at,
        "enabled": key_info.get("enabled", True)
    }


LOG_FILE_PATH = os.path.join(os.path.dirname(__file__), "api_requests.log")
LOG_LOCK = threading.Lock()

def write_api_log(log_entry: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {log_entry}\n"
    try:
        print(formatted.strip())
    except Exception:
        pass
    with LOG_LOCK:
        try:
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(formatted)
        except Exception:
            pass


def create_app():
    """
    FastAPI app matching UcBot and standard reseller API documentation specifications.
    Supports GET, POST JSON, and POST Form Data for both single and multi-code requests.
    Includes API Key authentication, per-key Rate Limiting, and full API logging.
    Endpoints:
      - / or /topup (Standard reseller response)
      - /topup-sync (UcBot JSON documentation format)
      - /credits, /balance, /status (UcBot status & balance)
    """
    import asyncio
    from fastapi import FastAPI, Request, Query
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Free Fire TopUp API", version="2.0")



    async def parse_request_params(
        request: Request,
        uid=None, playerid=None, code=None, redeem_code=None, vouchers=None, api_key=None, key=None
    ):
        target_uid = uid or playerid
        target_code = code or redeem_code or vouchers
        target_key = api_key or key
        order_id = None
        cookies = None

        # Extract Authorization header if present
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                target_key = target_key or auth_header.split(" ", 1)[1].strip()
            else:
                target_key = target_key or auth_header.strip()

        target_key = target_key or request.headers.get("X-API-Key") or request.headers.get("api_key") or request.headers.get("apikey")

        if request.method == "POST":
            raw_body = await request.body()
            if raw_body:
                try:
                    body_json = json.loads(raw_body.decode('utf-8'))
                    if isinstance(body_json, dict):
                        target_uid = target_uid or body_json.get("uid") or body_json.get("playerid") or body_json.get("login_id")
                        target_code = target_code or body_json.get("code") or body_json.get("redeem_code") or body_json.get("vouchers")
                        target_key = target_key or body_json.get("api_key") or body_json.get("apikey") or body_json.get("key")
                        order_id = body_json.get("orderid") or body_json.get("order_id")
                        cookies = body_json.get("cookies")
                except Exception:
                    pass

                if not target_uid or not target_code or not target_key:
                    try:
                        from urllib.parse import parse_qs
                        parsed_form = parse_qs(raw_body.decode('utf-8'))
                        def get_first(k):
                            v = parsed_form.get(k)
                            return v[0] if v else None
                        target_uid = target_uid or get_first("uid") or get_first("playerid") or get_first("login_id")
                        target_code = target_code or get_first("code") or get_first("redeem_code") or get_first("vouchers")
                        target_key = target_key or get_first("api_key") or get_first("apikey") or get_first("key")
                        order_id = order_id or get_first("orderid") or get_first("order_id")
                        cookies = cookies or get_first("cookies")
                    except Exception:
                        pass

        return str(target_uid or "").strip(), str(target_code or "").strip(), str(target_key or "").strip(), order_id, cookies

    @app.api_route("/", methods=["GET", "POST"])
    @app.api_route("/topup", methods=["GET", "POST"])
    async def api_general_topup(
        request: Request,
        uid: str | None = Query(None),
        playerid: str | None = Query(None),
        code: str | None = Query(None),
        redeem_code: str | None = Query(None),
        vouchers: str | None = Query(None),
        api_key: str | None = Query(None),
        key: str | None = Query(None),
    ):
        target_uid, target_code, target_key, order_id, cookies = await parse_request_params(
            request, uid, playerid, code, redeem_code, vouchers, api_key, key
        )

        is_valid, err_msg, status_code = check_api_key_and_rate_limit(target_key)
        if not is_valid:
            return JSONResponse(content={"success": False, "error": err_msg}, status_code=status_code)

        if not target_uid:
            return JSONResponse(content={"success": False, "error": "uid (login ID / playerid) required"}, status_code=400)
        if not target_code:
            return JSONResponse(content={"success": False, "error": "code / redeem_code required"}, status_code=400)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, process_multi_vouchers, target_uid, target_code, cookies
        )
        return JSONResponse(content=result, status_code=200)

    @app.api_route("/topup-sync", methods=["POST", "GET"])
    async def api_ucbot_topup_sync(
        request: Request,
        uid: str | None = Query(None),
        playerid: str | None = Query(None),
        code: str | None = Query(None),
        redeem_code: str | None = Query(None),
        vouchers: str | None = Query(None),
        api_key: str | None = Query(None),
        key: str | None = Query(None),
    ):
        target_uid, target_code, target_key, order_id, cookies = await parse_request_params(
            request, uid, playerid, code, redeem_code, vouchers, api_key, key
        )

        is_valid, err_msg, status_code = check_api_key_and_rate_limit(target_key)
        if not is_valid:
            return JSONResponse(content={"status": "error", "message": err_msg}, status_code=status_code)

        if not target_uid:
            return JSONResponse(content={"status": "error", "message": "playerid / uid required"}, status_code=400)
        if not target_code:
            return JSONResponse(content={"status": "error", "message": "code / vouchers required"}, status_code=400)

        loop = asyncio.get_running_loop()
        raw_res = await loop.run_in_executor(
            None, process_multi_vouchers, target_uid, target_code, cookies
        )

        raw_codes = [c.strip() for c in re.split(r'[,\r\n]+', str(target_code or '')) if c.strip()]
        results_list = raw_res.get("results") if "results" in raw_res else ([raw_res.get("result")] if raw_res.get("result") else [])
        player_nickname = ""
        for r in results_list:
            if isinstance(r, dict) and r.get("NickName"):
                player_nickname = r.get("NickName")
                break

        formatted_batch = []
        for i, r in enumerate(results_list):
            if isinstance(r, dict):
                is_ok = (str(r.get("Status") or "").upper() == "SUCCESS")
                err_detail = r.get("Error Message") or r.get("Error") or ("" if is_ok else "Failed")
                uc_code = r.get("UnipinCode") or (raw_codes[i] if i < len(raw_codes) else "")
                formatted_batch.append({
                    "ok": is_ok,
                    "uc": uc_code,
                    "detail": "" if is_ok else err_detail,
                    "code": uc_code,
                    "item": r.get("Item", ""),
                    "status": "SUCCESS" if is_ok else "FAILED",
                    "message": "Completed" if is_ok else err_detail,
                    "transaction_no": r.get("Transaction NO", ""),
                    "amount": r.get("Transaction Amount", ""),
                    "url": r.get("URL", "")
                })
            else:
                uc_code = raw_codes[i] if i < len(raw_codes) else ""
                formatted_batch.append({
                    "ok": False,
                    "uc": uc_code,
                    "detail": str(r),
                    "code": uc_code,
                    "item": "",
                    "status": "FAILED",
                    "message": str(r),
                    "transaction_no": "",
                    "amount": "",
                    "url": ""
                })

        response_payload = {
            "batch": formatted_batch,
            "failed": sum(1 for d in formatted_batch if not d["ok"]),
            "status": "success",
            "success": sum(1 for d in formatted_batch if d["ok"]),
            "total": len(formatted_batch),
            "username": player_nickname,
            "orderid": order_id or "ORD-SYNC",
            "playerid": target_uid,
            "nickname": player_nickname,
            "total_codes": len(formatted_batch),
            "successful_codes": sum(1 for d in formatted_batch if d["ok"]),
            "failed_codes": sum(1 for d in formatted_batch if not d["ok"]),
            "data": formatted_batch
        }

        is_batch = len(raw_codes) > 1
        item_names = [r.get("Item", "") for r in results_list if isinstance(r, dict) and r.get("Item")]
        amount_str = item_names[0] if item_names else "Topup"
        api_url = str(request.url).split("?")[0]

        if is_batch:
            call_log = f"CALL_BATCH url={api_url} uid={target_uid} amount={amount_str} codes={target_code}"
            resp_log = f"RESP_BATCH status=200 body={json.dumps(response_payload, ensure_ascii=False)}"
        else:
            call_log = f"CALL_SINGLE url={api_url} uid={target_uid} amount={amount_str} code={target_code}"
            resp_log = f"RESP_SINGLE status=200 body={json.dumps(response_payload, ensure_ascii=False)}"

        write_api_log(call_log)
        write_api_log(resp_log)
        return JSONResponse(content=response_payload, status_code=200)

    @app.api_route("/credits", methods=["GET", "POST"])
    @app.api_route("/credits/{api_key_path}", methods=["GET", "POST"])
    @app.api_route("/balance", methods=["GET", "POST"])
    @app.api_route("/balance/{api_key_path}", methods=["GET", "POST"])
    @app.api_route("/status", methods=["GET", "POST"])
    @app.api_route("/status/{api_key_path}", methods=["GET", "POST"])
    async def api_get_credits(
        request: Request,
        api_key_path: str | None = None,
        api_key: str | None = Query(None),
        key: str | None = Query(None),
    ):
        target_uid, target_code, target_key, order_id, cookies = await parse_request_params(
            request, api_key=api_key or api_key_path, key=key
        )
        target_key = target_key or api_key_path
        info = get_key_status_info(target_key)
        status_code = 200 if info.get("status") == "success" else 401
        return JSONResponse(content=info, status_code=status_code)

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=5987)
