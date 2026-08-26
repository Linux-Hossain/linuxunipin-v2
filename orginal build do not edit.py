from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import cloudscraper
from bs4 import BeautifulSoup
import re
import json
import os
from urllib.parse import urlencode

app = Flask(__name__)

POST_METHOD = True  # True করলে GET API বন্ধ হয়ে POST মেথডে কাজ করবে
VALID_API_KEY = "flexbase2026"  # API Key

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

def garena_payment_init(player_id: str):
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'android',
            'desktop': False
        }
    )

    
    scraper.get("https://shop.garena.my")
    mspid2 = scraper.cookies.get('mspid2', '')
    
    if not mspid2:
        return {"status": "error", "message": "mspid2 not found! Check VPN/IP."}

    
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
    except:
        return {"status": "error", "message": "Login data could not be collected."}

    new_datadome = scraper.cookies.get('datadome', '')
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
    except:
        return {"status": "error", "message": "Roles not found or verification failed."}

    preflight_url = "https://shop.garena.my/api/preflight"
    preflight_res = scraper.post(preflight_url, headers=role_headers)
    set_cookie = preflight_res.headers.get('Set-Cookie', '')
    csrf_match = re.search(r'__csrf__=([^;]+)', set_cookie)
    new_csrf = csrf_match.group(1) if csrf_match else "zS2n83MSRfrWe4o7cGvWAL6G9en6W5s7"

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
            return {"status": "success", "url": init_url, "nickname": login_nickname, "region": login_region}
        return {"status": "error", "message": "Init URL not found in response"}
    except:
        return {"status": "error", "message": "Failed to fetch payment init URL"}



def execute_redeem(input_url, packageId, user_input):
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'desktop': False})
    
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
            "cookie": f"region=BGD; __Host-XSRF-TOKEN={xsrf_4}; unipin_session={session_4}; _tt_enable_cookie=1; _ttp=01KMPH66ZA1R8C2S27SPNJ6ANS_.tt.1; _scid=bAa4BzLCsUkwN-VwL81TU50bdIxsEyT6; _scid_r=bAa4BzLCsUkwN-VwL81TU50bdIxsEyT6; _sc_cspv=https%3A%2F%2Ftr.snapchat.com",
            "priority": "u=0, i"
        }
        res5 = scraper.get(voucher_url, headers=headers5)
        
        c5 = scraper.cookies.get_dict()
        xsrf_5 = c5.get('__Host-XSRF-TOKEN', xsrf_4)
        session_5 = c5.get('unipin_session', session_4)

        
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

        elif "Consumed%20Voucher" in final_res.text:
            return {"status": "error", "message": "Consumed Voucher (Already Used)"}

        else:
            msg_tag = final_soup.find('h1', class_='title-case-0')
            return {"status": "error", "message": msg_tag.get_text(strip=True) if msg_tag else 'Unknown Error'}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.route("/api/unipin", methods=["GET", "POST"])
def unipin_api():
    if POST_METHOD and request.method != "POST":
        return jsonify({"status": "error", "message": "Only POST method is allowed."}), 405
    if not POST_METHOD and request.method != "GET":
        return jsonify({"status": "error", "message": "Only GET method is allowed."}), 405

    data = request.get_json(silent=True) or request.form.to_dict() if request.method == "POST" else request.args.to_dict()

    uid = data.get("uid")
    packageId = data.get("packageId")
    code = data.get("code")
    api_key = data.get("apiKey")

    if api_key != VALID_API_KEY:
        return jsonify({"status": "error", "message": "Invalid API Key"}), 401
    if not all([uid, packageId, code]):
        return jsonify({"status": "error", "message": "Missing required parameters: uid, packageId, code"}), 400
    if packageId not in DENOM_LIST:
        return jsonify({"status": "error", "message": "Invalid packageId"}), 400

    init_res = garena_payment_init(str(uid))
    if init_res["status"] == "error":
        log_data("failed.json", {"uid": uid, "packageId": packageId, "code": code, "error": init_res["message"]})
        return jsonify({"status": "failed", "message": init_res["message"]})

    
    redeem_res = execute_redeem(init_res["url"], packageId, code)

    log_record = {
        "uid": uid,
        "nickname": init_res["nickname"],
        "region": init_res["region"],
        "package": DENOM_LIST[packageId]["name"],
        "code": code,
        "response": redeem_res
    }

    if redeem_res["status"] == "success":
        log_data("transaction.json", log_record)
        return jsonify({"status": "success", "player": {"uid": uid, "nickname": init_res["nickname"], "region": init_res["region"]}, "transaction": redeem_res["details"]})
    else:
        log_data("failed.json", log_record)
        return jsonify({"status": "failed", "player": {"uid": uid, "nickname": init_res["nickname"]}, "region": init_res["region"], "message": redeem_res["message"]})



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

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Flexbase Unipin API Hub</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
            .glass-card {{
                background: rgba(30, 41, 59, 0.7);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(51, 65, 85, 0.6);
            }}
            .glow-effect {{
                box-shadow: 0 0 25px -5px rgba(59, 130, 246, 0.15);
            }}
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen p-6 md:p-10 selection:bg-blue-500 selection:text-white">
        <div class="max-w-4xl mx-auto">
            <header class="mb-10 text-center">
                <div class="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold uppercase tracking-wider mb-3">
                    <span class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
                    Flexbase Gateway Live
                </div>
                <h1 class="text-3xl md:text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 mb-2">
                    Flexbase API Hub
                </h1>
                <p class="text-slate-400 text-xs md:text-sm">Automated Garena Free Fire Unipin Top-up Gateway</p>
            </header>

            <!-- API Documentation Section (Both GET & POST) -->
            <div class="glass-card rounded-2xl p-6 mb-8 glow-effect">
                <div class="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
                    <h2 class="text-lg font-bold text-blue-400">API Documentation</h2>
                    <span class="px-3 py-1 rounded-full text-xs font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        Supports: GET & POST
                    </span>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <!-- GET Method Box -->
                    <div class="bg-slate-900/90 border border-slate-800/80 p-4 rounded-xl">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-xs font-bold text-amber-400">GET Method (Query Params)</span>
                        </div>
                        <div class="text-xs text-emerald-400 font-mono overflow-x-auto bg-slate-950 p-2.5 rounded border border-slate-900">
                            /api/unipin?uid=&#123;uid&#125;&packageId=&#123;id&#125;&code=&#123;voucher&#125;&apiKey=&#123;key&#125;
                        </div>
                    </div>

                    <!-- POST Method Box -->
                    <div class="bg-slate-900/90 border border-slate-800/80 p-4 rounded-xl">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-xs font-bold text-emerald-400">POST Method (JSON Body)</span>
                        </div>
                        <pre class="text-xs text-emerald-400 font-mono overflow-x-auto bg-slate-950 p-2.5 rounded border border-slate-900">
POST /api/unipin
Content-Type: application/json

{{
  "uid": "228197025",
  "packageId": "1",
  "code": "BDMB-T-S-xxxxxx xxxx-xxxx",
  "apiKey": "your_api_key"
}}</pre>
                    </div>
                </div>
            </div>

            <h2 class="text-xl font-bold mb-4 text-slate-200 border-b border-slate-800 pb-2">Available Package IDs</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
                {packages_html}
            </div>

            <footer class="mt-14 text-center text-xs text-slate-500 border-t border-slate-900 pt-5">
                &copy; 2026 <span class="text-slate-400 font-semibold">Flexbase</span>. Powered by Flask.
            </footer>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_content)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
