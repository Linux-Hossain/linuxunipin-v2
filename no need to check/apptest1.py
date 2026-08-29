from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
from curl_cffi import requests
from bs4 import BeautifulSoup
import os
import json
import re
import threading
from dotenv import load_dotenv
import itertools
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode
import random

load_dotenv()

app = Flask(__name__)

POST_METHOD = True  # True করলে GET API বন্ধ হয়ে POST মেথডে কাজ করবে
VALID_API_KEY = "flexbase2026"  # API Key
SUBSCRIPTIONS_FILE = os.getenv("SUBSCRIPTIONS_FILE", "logs/subscriptions.json")
SUBSCRIPTIONS_LOCK = threading.Lock()

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

PREFIX_MAP = {
    "BDMB-T-S": "1", "BDMB-U-S": "2", "BDMB-J-S": "3", "BDMB-I-S": "4",
    "BDMB-K-S": "5", "BDMB-L-S": "6", "BDMB-M-S": "7", "BDMB-Q-S": "8", "BDMB-S-S": "9",
    "UPBD-Q-S": "1", "UPBD-R-S": "2", "UPBD-G-S": "3", "UPBD-F-S": "4",
    "UPBD-H-S": "5", "UPBD-I-S": "6", "UPBD-J-S": "7", "UPBD-N-S": "8", "UPBD-P-S": "9",
}

PROXY_POOL = [
    "cghgkxjs-MY-rotate", "cghgkxjs-my-1", "cghgkxjs-my-2", "cghgkxjs-my-3", "cghgkxjs-my-4", "cghgkxjs-my-5",
    "cghgkxjs-my-6", "cghgkxjs-my-7", "cghgkxjs-my-8", "cghgkxjs-my-9", "cghgkxjs-my-10"
]
PROXY_CYCLE = itertools.cycle(PROXY_POOL)
PROXY_LOCK = threading.Lock()

def new_garena_scraper():
    scraper = requests.Session(impersonate="chrome120")
    return scraper

def load_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_subscriptions(data):
    temporary_file = f"{SUBSCRIPTIONS_FILE}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
    os.replace(temporary_file, SUBSCRIPTIONS_FILE)

def subscription_error(api_key):
    with SUBSCRIPTIONS_LOCK:
        record = load_subscriptions().get(api_key)
        if not record:
            return "Invalid API token"
        if record.get("active", True) is not True:
            return "API subscription is inactive"
        expires_at = record.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now().astimezone():
            return "API subscription expired"
        max_requests = int(record.get("max_requests", -1))
        used_requests = int(record.get("used_requests", 0))
        if max_requests >= 0 and used_requests >= max_requests:
            return "API request limit exhausted"
        record["used_requests"] = used_requests + 1
        record["updated_at"] = datetime.now().astimezone().isoformat()
        data = load_subscriptions()
        data[api_key] = record
        save_subscriptions(data)
    return None

def package_for_code(code):
    prefix = "-".join(code.strip().upper().split()[0].split("-")[:3])
    return PREFIX_MAP.get(prefix)

def log_data(filename: str, data: dict):
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
            json.dump(logs, f, indent=4)
    except Exception as e:
        print(f"[!] Log File Error: {e}")

def garena_payment_init(player_id: str, session_data=None):
    if session_data is None:
        login_nickname = ''
        login_region = ''
        scraper = None
        mspid2 = ''
        datadome = ''

        for attempt in range(3):
            scraper = new_garena_scraper()

            init_headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }
            try:
                res_init = scraper.get("https://shop.garena.my", headers=init_headers)
                mspid2 = scraper.cookies.get('mspid2', '')
                datadome = scraper.cookies.get('datadome', '')
            except Exception:
                continue

            if not datadome:
                try:
                    js_res = scraper.post("https://datadome.garena.com/js/", data=urlencode({
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
                except Exception:
                    pass

            login_url = "https://shop.garena.my/api/auth/player_id_login"
            region = scraper.cookies.get('region', 'MY')
            
            login_headers = {
                "Host": "shop.garena.my",
                "Connection": "keep-alive",
                "sec-ch-ua-platform": "\"Android\"",
                "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "sec-ch-ua": "\"Chromium\";v=\"120\", \"Not-A.Brand\";v=\"24\", \"Android WebView\";v=\"120\"",
                "Content-Type": "application/json",
                "sec-ch-ua-mobile": "?1",
                "Accept": "*/*",
                "Origin": "https://shop.garena.my",
                "Referer": "https://shop.garena.my/?channel=202953",
                "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; datadome={datadome}"
            }
            
            login_payload = {"app_id": 100067, "login_id": player_id}
            
            try:
                login_res = scraper.post(login_url, headers=login_headers, json=login_payload)
                if login_res.status_code == 200:
                    login_data = login_res.json()
                    login_nickname = login_data.get('nickname', '')
                    login_region = login_data.get('region', '')
                    if login_nickname:
                        break
                elif login_res.status_code == 403:
                    data = login_res.json() if login_res.headers.get('content-type', '').startswith('application/json') else {}
                    cap_url = data.get("url")
                    if cap_url:
                        scraper.get(cap_url, headers={"Referer": "https://shop.garena.my/"})
                        new_dd = scraper.cookies.get('datadome', datadome)
                        login_headers["Cookie"] = f"source=mb; region=MY; language=en; mspid2={mspid2}; datadome={new_dd}"
                        retry_res = scraper.post(login_url, headers=login_headers, json=login_payload)
                        if retry_res.status_code == 200:
                            login_data = retry_res.json()
                            login_nickname = login_data.get('nickname', '')
                            login_region = login_data.get('region', '')
                            if login_nickname:
                                break
                    if login_nickname:
                        break
            except Exception:
                pass

        if not login_nickname:
            return {"status": "error", "message": "Invalid Player ID or empty nickname"}

        new_datadome = scraper.cookies.get('datadome', datadome)
        session_key = scraper.cookies.get('session_key', '')

        if not session_key:
            return {"status": "error", "message": "Session Key Not found."}

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
            "Cookie": f"source=mb; region=MY; language=en; mspid2={mspid2}; __csrf__=zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7; datadome={new_datadome}; session_key={session_key}"
        }

        try:
            role_res = scraper.get(role_url, headers=role_headers)
            role_data = role_res.json()
            player_info = role_data.get("100067", [])[0]
            
            role_nickname = player_info.get("role", "")
            role_region = player_info.get("region", "")

            if role_nickname != login_nickname or role_region != login_region:
                return {"status": "error", "message": f"Verification Failed! Mismatch: Expected {login_nickname}, Found {role_nickname}"}
        except:
            return {"status": "error", "message": "Roles not found or verification failed."}

        preflight_url = "https://shop.garena.my/api/preflight"
        preflight_res = scraper.post(preflight_url, headers=role_headers)
        set_cookie = preflight_res.headers.get('Set-Cookie', '')
        csrf_match = re.search(r'__csrf__=([^;]+)', set_cookie)
        new_csrf = csrf_match.group(1) if csrf_match else "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"

        session_data = {
            "scraper": scraper,
            "mspid2": mspid2,
            "session_key": session_key,
            "new_datadome": new_datadome,
            "new_csrf": new_csrf,
            "login_nickname": login_nickname,
            "login_region": login_region
        }

    scraper = session_data["scraper"]
    mspid2 = session_data["mspid2"]
    session_key = session_data["session_key"]
    new_datadome = session_data["new_datadome"]
    new_csrf = session_data["new_csrf"]
    login_nickname = session_data["login_nickname"]
    login_region = session_data["login_region"]

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
        "revamp_experiment": {"session_id": mspid2, "group": "treatment2", "service_version": "mshop_frontend_20260324", "source": "mb", "domain": "shop.garena.my"}
    }

    try:
        final_res = scraper.post(pay_init_url, headers=pay_headers, json=pay_payload)
        init_url = final_res.json().get('init', {}).get('url', '')
        if init_url:
            return {"status": "success", "url": init_url, "nickname": login_nickname, "region": login_region, "session_data": session_data}
        return {"status": "error", "message": "Init URL not found in response"}
    except:
        return {"status": "error", "message": "Failed to fetch payment init URL"}

def execute_redeem(input_url, packageId, user_input):
    if os.getenv('PROXY_MODE', 'garena_only') == 'all':
        scraper = new_garena_scraper()
    else:
        scraper = requests.Session(impersonate="chrome120")
    
    match = re.search(r'/unibox/d/([^?]+)', input_url)
    if not match: 
        return {"status": "error", "message": "Invalid Unique ID in URL"}
    unique_id = match.group(1)

    try:
        res1 = scraper.get(input_url, headers={
            "user-agent": "Mozilla/5.0 (Linux; Android 13; M2101K7BG Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.119 Mobile Safari/537.36",
            "referer": "https://shop.garena.my/"
        })
        
        c1 = scraper.cookies.get_dict()
        xsrf_1 = c1.get('__Host-XSRF-TOKEN', '')
        session_1 = c1.get('unipin_session', '')

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

        parts = user_input.strip().split(" ")
        clean_serial = parts[0].replace("-", "")
        pin_parts = parts[1].split("-")
        path_id = "659" if clean_serial.startswith("BDMB") else "670"

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
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_3}; unipin_session={session_3}; _tt_enable_cookie=1; _ttp=01KMPH66ZA1R8C2S27SPNJ6ANS_.tt.1; _scid=bAa4BzLCsUkwN-VwL81TU50bdIxsEyT6; _scid_r=bAa4BzLCsUkwN-VwL81TU50bdIxsEyT6; _sc_cspv=https%3A%2F%2Ftr.snapchat.com",
            "priority": "u=0, i"
        }
        res5 = scraper.get(voucher_url, headers=headers5)
        
        c5 = scraper.cookies.get_dict()
        xsrf_5 = c5.get('__Host-XSRF-TOKEN', xsrf_3)
        session_5 = c5.get('unipin_session', session_3)

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
            "pin_1": pin_parts[0], "pin_2": pin_parts[1], 
            "pin_3": pin_parts[2], "pin_4": pin_parts[3]
        }
        
        final_res = scraper.post(final_post_url, data=urlencode(final_payload), headers=headers6)
        final_soup = BeautifulSoup(final_res.text, 'html.parser')

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

        elif "Consumed%20Voucher" in final_res.text or "Consumed Voucher" in final_res.text or final_soup.find(string=re.compile("Consumed Voucher")):
            return {"status": "error", "message": "Consumed Voucher (Already Used)"}

        else:
            msg_tag = final_soup.find('h1', class_='title-case-0')
            return {"status": "error", "message": msg_tag.get_text(strip=True) if msg_tag else 'Unknown Error'}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.route("/topup-sync", methods=["POST"])
@app.route("/api/unipin", methods=["POST"])
def unipin_api():
    data = request.get_json(silent=True) or request.form.to_dict()

    uid = data.get("playerid") or data.get("uid")
    code_value = data.get("code") or data.get("voucher")
    orderid = data.get("orderid", "")
    api_key = data.get("apiKey") or data.get("api_key") or data.get("apikey")
    package_id = data.get("packageId") or data.get("package_id") or data.get("amount")

    if api_key != VALID_API_KEY:
        return jsonify({"status": "error", "message": "Invalid API Key"}), 401
    codes = [item.strip() for item in str(code_value or "").split(",") if item.strip()]
    if not uid or not orderid or not codes:
        return jsonify({"status": "error", "message": "Missing required parameters: orderid, playerid, code"}), 400
    if len(codes) > 5:
        return jsonify({"status": "error", "message": "Maximum 5 codes allowed"}), 400

    init_res = garena_payment_init(str(uid))
    if init_res["status"] == "error":
        return jsonify({
            "status": "failed",
            "orderid": orderid,
            "nickname": "N/A",
            "username": "N/A",
            "region": "BD",
            "success": 0,
            "failed": len(codes),
            "total": len(codes),
            "batch": [{"uc": code, "ok": False, "detail": init_res["message"]} for code in codes]
        })

    active_session_data = init_res.get("session_data")
    nickname = init_res.get("nickname", "N/A")
    region = init_res.get("region", "BD")

    def process_code(code):
        current_package = package_id or package_for_code(code)
        if current_package not in DENOM_LIST:
            return {"uc": code, "ok": False, "detail": "Invalid packageId"}
        
        pay_res = garena_payment_init(str(uid), session_data=active_session_data)
        if pay_res["status"] == "error":
            return {"uc": code, "ok": False, "detail": pay_res["message"]}
        
        redeem_res = execute_redeem(pay_res["url"], current_package, code)
        ok = redeem_res["status"] == "success"
        item = {
            "uc": code,
            "ok": ok,
            "detail": "Success" if ok else redeem_res.get("message", "Transaction Failed")
        }
        if ok and "details" in redeem_res:
            item["trx_id"] = redeem_res["details"].get("trans_no", "")
            item["receipt"] = redeem_res["details"]
        return item

    with ThreadPoolExecutor(max_workers=min(len(codes), 5)) as executor:
        batch = list(executor.map(process_code, codes))

    success = sum(1 for item in batch if item["ok"])
    failed = len(batch) - success
    status_value = "success" if failed == 0 else "failed" if success == 0 else "partial"
    return jsonify({"status": status_value, "orderid": orderid, "nickname": nickname, "username": nickname, "region": region, "success": success, "failed": failed, "total": len(batch), "batch": batch})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000, debug=False, threaded=True)
