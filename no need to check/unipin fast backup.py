import requests
import json
import re
import os
import cloudscraper
from urllib.parse import urlencode, quote, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

load_dotenv()


def create_garena_session():
    session = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'android', 'desktop': False}
    )
    if os.getenv('WEBSHARE_ENABLED', 'false').lower() == 'true':
        host = os.getenv('WEBSHARE_HOST', '')
        port = os.getenv('WEBSHARE_PORT', '')
        user = quote(os.getenv('WEBSHARE_USER', ''), safe='')
        password = quote(os.getenv('WEBSHARE_PASS', ''), safe='')
        if host and port and user and password:
            proxy = f'http://{user}:{password}@{host}:{port}'
            session.proxies.update({'http': proxy, 'https': proxy})
    session.get('https://shop.garena.my/', headers={
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/146 Mobile Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }, timeout=20)
    return session

def login_request(app_id, login_id, cookies=None, session=None):
    """
    Make a login request to Garena shop API
    """
    if session is None:
        session = create_garena_session()

    url = 'https://shop.garena.my/api/auth/player_id_login'

    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'https://shop.garena.my',
        'Pragma': 'no-cache',
        'Referer': 'https://shop.garena.my/?channel=202953',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"'
    }

    data = {
        "app_id": app_id,
        "login_id": login_id
    }

    # Parse cookies if provided as string
    if cookies:
        if isinstance(cookies, str):
            cookie_dict = {}
            for item in cookies.split('; '):
                if '=' in item:
                    key, value = item.split('=', 1)
                    cookie_dict[key] = value
            cookies = cookie_dict

        # Set cookies in session
        for key, value in cookies.items():
            session.cookies.set(key, value)

    response = session.post(url, headers=headers, json=data)
    return response, session


def proceed_to_payment(app_id, channel_id=221179, region="MY", language="en", packed_role_id=0, session=None, csrf_token=None):
    """
    Proceed to payment after login - Initialize payment
    """
    if session is None:
        raise ValueError("Session object is required for payment request")

    url = f'https://shop.garena.my/api/shop/pay/init?region={region}&language={language}'

    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'https://shop.garena.my',
        'Pragma': 'no-cache',
        'Referer': 'https://shop.garena.my/?channel=202953',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"'
    }

    # Extract CSRF token from session cookies if not provided
    if not csrf_token:
        csrf_token = session.cookies.get('__csrf__')

    # Extract session_id (mspid2) from session cookies
    session_id = session.cookies.get('mspid2')
    if not session_id:
        raise ValueError('Fresh Garena session cookie mspid2 not found')

    # Add CSRF token to headers if available
    if csrf_token:
        headers['x-csrf-token'] = csrf_token

    # Build request data
    data = {
        "app_id": app_id,
        "packed_role_id": packed_role_id,
        "channel_id": channel_id,
        "service": "pc",
        "channel_data": {
            "need_return": True,
            "payment_channel": None
        },
        "revamp_experiment": {
            "session_id": session_id,
            "group": "treatment2",
            "service_version": "mshop_frontend_20260115",
            "source": "pc",
            "domain": "shop.garena.my"
        }
    }

    response = session.post(url, headers=headers, json=data)
    return response


def select_denomination_unipin(session, unipin_url, denomination_data):
    """
    Select a denomination on UniPin page
    """
    print("Debug: Visiting /d/ page first to establish session...")
    try:
        page_response = session.get(unipin_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://shop.garena.my/'
        }, allow_redirects=True)
    except ValueError as e:
        if 'multiple cookies' in str(e).lower():
            # Cookie conflict error - try to continue
            page_response = session.get(unipin_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://shop.garena.my/'
            }, allow_redirects=True)
        else:
            raise

    # The /d/ page redirects to /select_denom/, so form_url is the final redirected URL
    form_url = page_response.url
    if '/select_denom/' not in form_url:
        form_url = unipin_url.replace('/d/', '/select_denom/')

    # Extract CSRF token
    csrf_match = re.search(
        r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', page_response.text)
    if not csrf_match:
        csrf_match = re.search(
            r'<input[^>]+name="_token"[^>]+value="([^"]+)"', page_response.text)

    csrf_token = csrf_match.group(1) if csrf_match else None

    # URL-encode the denomination JSON
    denom_json = json.dumps(denomination_data, separators=(',', ':'))
    denom_encoded = quote(denom_json, safe='')

    form_data_str = f"_token={csrf_token or ''}&denomination={denom_encoded}"

    response = session.post(
        form_url,
        data=form_data_str,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': form_url,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://www.unipin.com',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Upgrade-Insecure-Requests': '1'
        },
        allow_redirects=True
    )
    return response


def get_payment_channel_links(checkout_url):
    """
    Extract payment channel links from checkout URL
    """
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
    """
    denominations = []
    pattern = r"onclick=\"submit_form\('({[^']+})'\)\""
    matches = re.findall(pattern, html_content)

    for match in matches:
        try:
            json_str = match.replace('&quot;', '"')
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


def process_transaction(uid, amount_query, voucher_code):
    """
    Process the full transaction flow
    """
    result = {
        'UID': uid,
        'NickName': 'N/A',
        'UnipinCode': voucher_code,
        'Item': '',
        'Date': '',
        'Transaction NO': '',
        'Reference': '',
        'Transaction Amount': '',
        'Status': 'FAILED',
        'Error': '',
        'Error Message': '',
        'URL': ''
    }

    # 1. Login with a fresh proxied session and newly issued cookies
    print(f"Logging in with UID: {uid}")
    
    try:
        response, session = login_request(100067, uid)
        login_data = response.json()
        
        if response.status_code != 200 or 'open_id' not in login_data:
            result['Error'] = 'Login Failed'
            result['Error Message'] = 'Could not login to Garena shop. Check UID.'
            return result
            
        result['NickName'] = login_data.get('nickname', 'N/A')
        
    except Exception as e:
        result['Error'] = 'Request Error'
        result['Error Message'] = str(e)
        return result

    # 2. Proceed to payment (get UniPin URL)
    print("Initializing payment...")
    try:
        payment_response = proceed_to_payment(100067, channel_id=221179, session=session)
        payment_data = payment_response.json()
        
        if payment_data.get('result') != 'success' or 'init' not in payment_data or 'url' not in payment_data['init']:
            result['Error'] = 'Payment Init Failed'
            result['Error Message'] = 'Could not initialize UniPin payment.'
            return result
            
        unipin_url = payment_data['init']['url']
        
    except Exception as e:
        result['Error'] = 'Payment Request Error'
        result['Error Message'] = str(e)
        return result

    # 3. Process UniPin (Select Denom -> Select Channel -> Submit Code)
    try:
        # Create separate session for UniPin
        unipin_session = requests.Session()
        
        # Get Denominations
        print(f"Fetching UniPin page: {unipin_url}")
        unipin_response = unipin_session.get(unipin_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'Referer': 'https://shop.garena.my/'
        })
        
        denominations = parse_unipin_denominations(unipin_response.text)
        
        # Select matching denomination
        selected = None
        for denom in denominations:
            # Check if amount_query is in name (e.g. "25" in "25 Diamonds")
            if amount_query in denom['name']:
                selected = denom
                break
        
        if not selected:
            result['Error'] = 'Denomination Not Found'
            result['Error Message'] = f"Could not find a product matching '{amount_query}'"
            return result
            
        print(f"Selected product: {selected['name']}")
        result['Item'] = selected['name']
        
        # Submit Denomination
        submit_response = select_denomination_unipin(unipin_session, unipin_url, selected)
        
        # Verify we are on checkout
        is_checkout = ('checkout' in submit_response.text.lower() or 
                       'Select Payment Channel' in submit_response.text or 
                       'Wallet' in submit_response.text)
                       
        if not is_checkout:
            result['Error'] = 'Denomination Submission Failed'
            result['Error Message'] = "Failed to proceed to checkout page."
            return result
            
        # Get Channel Links
        channel_links = get_payment_channel_links(submit_response.url)
        
        selected_link = None
        
        # Auto-select channel based on code prefix
        if voucher_code.startswith('UPBD'):
            selected_link = channel_links.get('up_gift_card')
            print("Auto-selected Channel: UP Gift Card (UPBD)")
        elif voucher_code.startswith('BDMB'):
            selected_link = channel_links.get('unipin_voucher')
            print("Auto-selected Channel: UniPin Voucher (BDMB)")
        else:
            # Default fallback logic or error?
            # Let's try to guess or just default to UP Gift Card if unknown
             result['Error'] = 'Unknown Voucher Type'
             result['Error Message'] = "Code must start with UPBD or BDMB."
             return result

        if not selected_link:
             result['Error'] = 'Channel Not Available'
             result['Error Message'] = "Target payment channel is not available on checkout page."
             return result
             
        # Access Channel Page
        channel_response = unipin_session.get(selected_link, headers={
             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
             'Referer': submit_response.url,
             'Upgrade-Insecure-Requests': '1'
        })
        
        # Prepare Voucher Submission
        
        # 1. Parse content for CSRF and Form Action (similar to original script)
        csrf_match = re.search(r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', channel_response.text)
        if not csrf_match:
             csrf_match = re.search(r'<input[^>]+name="_token"[^>]+value="([^"]+)"', channel_response.text)
        csrf_token = csrf_match.group(1) if csrf_match else None
        
        form_action_match = re.search(r'<form[^>]+action="([^"]+)"', channel_response.text, re.IGNORECASE)
        form_action = form_action_match.group(1) if form_action_match else channel_response.url
        if form_action.startswith('/'):
             parsed = urlparse(channel_response.url)
             form_action = f"{parsed.scheme}://{parsed.netloc}{form_action}"
        if '?' in form_action:
             form_action = form_action.split('?')[0]
             
        # 2. Prepare Form Data
        form_data = {'_token': csrf_token or ''}
        
        # Split Code
        voucher_parts = voucher_code.split(' ', 1)
        serial_part = voucher_parts[0] if len(voucher_parts) > 0 else voucher_code
        pin_part = voucher_parts[1] if len(voucher_parts) > 1 else ""
        
        serial_cleaned = serial_part.replace('-', '').replace(' ', '')
        
        # Find serial field name
        all_inputs = re.findall(r'<input[^>]+name="([^"]+)"', channel_response.text, re.IGNORECASE)
        if 'serial' in all_inputs:
             form_data['serial'] = serial_cleaned
        else:
             # Fallback
             serial_match = re.search(r'name="([^"]*serial[^"]*)"', channel_response.text, re.IGNORECASE)
             if serial_match:
                 form_data[serial_match.group(1)] = serial_cleaned
             else:
                 form_data['serial'] = serial_cleaned

        # Handle PIN fields
        if pin_part:
             pin_segments = re.split(r'[- ]+', pin_part)
             pin_fields = re.findall(r'name="(pin_\d+)"', channel_response.text)
             if not pin_fields:
                 pin_fields = re.findall(r'name="(pin\d+)"', channel_response.text, re.IGNORECASE)
             
             if pin_fields:
                 sorted_pin = sorted(pin_fields)
                 for i, field in enumerate(sorted_pin):
                     if i < len(pin_segments):
                         form_data[field] = pin_segments[i]
                     else:
                         form_data[field] = ''
             else:
                 # Fallback pin_1, pin_2...
                 for i in range(1, 5):
                     if i <= len(pin_segments):
                         form_data[f'pin_{i}'] = pin_segments[i-1]

        # 3. Submit
        print(f"Submitting voucher to {form_action}")
        voucher_response = unipin_session.post(
             form_action,
             data=form_data,
             headers={
                  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
                  'Referer': channel_response.url,
                  'Origin': 'https://www.unipin.com'
             },
             allow_redirects=True
        )
        
        result['URL'] = voucher_response.url
        
        # 4. Parse Result (Success / Fail)
        response_text_lower = voucher_response.text.lower()
        
        # Error URL Check
        error_url_match = re.search(r'/unibox/error/([^/?]+)', voucher_response.url)
        if error_url_match:
             error_type = requests.utils.unquote(error_url_match.group(1))
             result['Error'] = error_type
             if 'consumed' in error_type.lower() or 'used' in error_type.lower():
                 result['Error Message'] = "This voucher has already been used/consumed."
             elif 'invalid' in error_type.lower():
                 result['Error Message'] = "This voucher code is invalid."
             elif 'expired' in error_type.lower():
                 result['Error Message'] = "This voucher has expired."
             else:
                 result['Error Message'] = error_type
             return result
             
        # Success Check
        success_indicators = ['success', 'transaction success', 'redeemed successfully', '/unibox/result/']
        is_success = any(i in response_text_lower or i in voucher_response.url.lower() for i in success_indicators)
        
        # Specific check for form fields cleared (also success indicator)
        if not is_success and '<form' in voucher_response.text: 
             # Check if fields are empty
             serial_val = re.search(r'name="serial"[^>]+value="([^"]*)"', voucher_response.text)
             if serial_val and not serial_val.group(1):
                  is_success = True
        
        if is_success:
             result['Status'] = 'SUCCESS'
             
             # Try to scrape details from JS or HTML
             presult_match = re.search(r'var\s+pResult\s*=\s*({[^}]+})', voucher_response.text, re.IGNORECASE | re.DOTALL)
             if presult_match:
                  try:
                       js_str = presult_match.group(1).replace("'", '"')
                       js_str = re.sub(r'(\w+)\s*:', r'"\1":', js_str)
                       p_data = json.loads(js_str)
                       if 'trxNo' in p_data: result['Transaction NO'] = p_data['trxNo']
                       if 'reference' in p_data: result['Reference'] = p_data['reference']
                       if 'amount' in p_data: result['Transaction Amount'] = p_data['amount']
                  except:
                       pass
                       
             # Additional HTML scraping
             details = re.findall(r'<div class="details-label">\s*(.*?)\s*</div>\s*<div class="details-value"[^>]*>\s*(.*?)\s*</div>', voucher_response.text, re.DOTALL)
             for label, val in details:
                  clean_val = re.sub(r'<[^>]+>', '', val).strip()
                  clean_val = " ".join(clean_val.split())
                  label = label.strip()
                  if 'Transaction No' in label: result['Transaction NO'] = clean_val
                  if 'Reference' in label: result['Reference'] = clean_val
                  if 'Date' in label: result['Date'] = clean_val
                  
             amount_match = re.search(r'<div class="checkout-amount">\s*(.*?)\s*</div>', voucher_response.text)
             if amount_match:
                  clean_amt = re.sub(r'<[^>]+>', '', amount_match.group(1)).strip()
                  result['Transaction Amount'] = clean_amt

        else:
             # Likely failed
             result['Status'] = 'FAILED'
             result['Error'] = 'Voucher Error'
             
             # Extract error message from page
             err_match = re.search(r'<div[^>]*class="[^"]*alert[^"]*"[^>]*>([^<]+)</div>', voucher_response.text)
             if not err_match:
                  err_match = re.search(r'<p[^>]*class="[^"]*error[^"]*"[^>]*>([^<]+)</p>', voucher_response.text)
             
             if err_match:
                  result['Error Message'] = err_match.group(1).strip()
             else:
                  result['Error Message'] = "Unknown error occurred during voucher submission."

    except Exception as e:
        result['Error'] = 'Processing Error'
        result['Error Message'] = str(e)
        
    return result


class UnipinHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)

        # Expect arguments: uid, amount, code
        if 'uid' not in query_params or 'amount' not in query_params or 'code' not in query_params:
            self.send_response(400)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            error_response = {
                'Status': 'ERROR',
                'Message': 'Missing parameters. required: uid, amount, code. Example: /?uid=123&amount=25&code=UPBD-...'
            }
            self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode('utf-8'))
            return

        uid = query_params['uid'][0]
        amount = query_params['amount'][0]
        code = query_params['code'][0]

        print(f"Received Request - UID: {uid}, Amount: {amount}, Code: {code}")

        # Process Transaction
        result = process_transaction(uid, amount, code)

        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(result, indent=2, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        # Silence default server logs to keep console clean for debug prints
        return


if __name__ == '__main__':
    PORT = 549
    server = HTTPServer(('localhost', PORT), UnipinHandler)
    print(f"UniPin API Server running on port {PORT}")
    print(f"Usage: http://localhost:{PORT}/?uid=PLAYER_ID&amount=PRODUCT_NAME&code=VOUCHER_CODE")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()
