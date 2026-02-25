import os, json, random, string, time, re, struct
import threading
import concurrent.futures
from urllib.parse import urljoin, urlparse
from curl_cffi import requests
from bs4 import BeautifulSoup

from g import EmailService, TurnstileService, UserAgreementService, NsfwSettingsService

# 基础配置
site_url = "https://accounts.x.ai"
DEFAULT_IMPERSONATE = "chrome120"
CHROME_PROFILES = [
    {"impersonate": "chrome110", "version": "110.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome119", "version": "119.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome120", "version": "120.0.0.0", "brand": "chrome"},
    {"impersonate": "edge99", "version": "99.0.1150.36", "brand": "edge"},
    {"impersonate": "edge101", "version": "101.0.1210.47", "brand": "edge"},
]

def get_random_chrome_profile():
    profile = random.choice(CHROME_PROFILES)
    if profile.get("brand") == "edge":
        chrome_major = profile["version"].split(".")[0]
        chrome_version = f"{chrome_major}.0.0.0"
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_version} Safari/537.36 Edg/{profile['version']}"
        )
    else:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{profile['version']} Safari/537.36"
        )
    return profile["impersonate"], ua

# 不使用代理，直连（家庭宽带）
def get_random_proxy():
    return None

# 动态获取的全局变量
config = {
    "site_key": "0x4AAAAAAAhr9JGVDZbrZOo0",
    "action_id": None,
    "state_tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(app)%22%2C%7B%22children%22%3A%5B%22(auth)%22%2C%7B%22children%22%3A%5B%22sign-up%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fsign-up%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%2Ctrue%5D"
}

post_lock = threading.Lock()
file_lock = threading.Lock()
print_lock = threading.Lock()
success_count = 0
start_time = time.time()
target_count = 100
stop_event = threading.Event()
output_file = None

def log(email, step, status, detail=""):
    ts = time.strftime("%H:%M:%S")
    short_email = email.split("@")[0] if email else "?"
    icons = {"info": "  ·", "ok": "  ✓", "fail": "  ✗", "warn": "  ⚠"}
    icon = icons.get(status, "  ·")
    msg = f"[{ts}] {icon} [{short_email}] {step}"
    if detail:
        msg += f"  →  {detail}"
    with print_lock:
        print(msg)

def generate_random_name() -> str:
    length = random.randint(4, 6)
    return random.choice(string.ascii_uppercase) + ''.join(random.choice(string.ascii_lowercase) for _ in range(length - 1))

def generate_random_string(length: int = 15) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))

def encode_grpc_message(field_id, string_value):
    key = (field_id << 3) | 2
    value_bytes = string_value.encode('utf-8')
    length = len(value_bytes)
    payload = struct.pack('B', key) + struct.pack('B', length) + value_bytes
    return b'\x00' + struct.pack('>I', len(payload)) + payload

def encode_grpc_message_verify(email, code):
    p1 = struct.pack('B', (1 << 3) | 2) + struct.pack('B', len(email)) + email.encode('utf-8')
    p2 = struct.pack('B', (2 << 3) | 2) + struct.pack('B', len(code)) + code.encode('utf-8')
    payload = p1 + p2
    return b'\x00' + struct.pack('>I', len(payload)) + payload

def send_email_code_grpc(session, email):
    url = f"{site_url}/auth_mgmt.AuthManagement/CreateEmailValidationCode"
    data = encode_grpc_message(1, email)
    headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": site_url,
        "referer": f"{site_url}/sign-up?redirect=grok-com"
    }
    try:
        res = session.post(url, data=data, headers=headers, timeout=15)
        if res.status_code == 200:
            return True, None
        else:
            return False, f"HTTP {res.status_code}"
    except Exception as e:
        return False, str(e)[:80]

def verify_email_code_grpc(session, email, code):
    url = f"{site_url}/auth_mgmt.AuthManagement/VerifyEmailValidationCode"
    data = encode_grpc_message_verify(email, code)
    headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": site_url,
        "referer": f"{site_url}/sign-up?redirect=grok-com"
    }
    try:
        res = session.post(url, data=data, headers=headers, timeout=15)
        if res.status_code == 200:
            return True, None
        else:
            return False, f"HTTP {res.status_code}"
    except Exception as e:
        return False, str(e)[:80]

def register_single_thread():
    time.sleep(random.uniform(0, 5))

    try:
        email_service = EmailService()
        turnstile_service = TurnstileService()
        user_agreement_service = UserAgreementService()
        nsfw_service = NsfwSettingsService()
    except Exception as e:
        with print_lock:
            print(f"[-] 服务初始化失败: {e}")
        return

    final_action_id = config["action_id"]
    if not final_action_id:
        with print_lock:
            print("[-] 线程退出：缺少 Action ID")
        return

    current_email = None

    while True:
        try:
            if stop_event.is_set():
                if current_email:
                    try: email_service.delete_email(current_email)
                    except: pass
                return

            impersonate_fingerprint, account_user_agent = get_random_chrome_profile()

            with requests.Session(impersonate=impersonate_fingerprint, proxies=get_random_proxy()) as session:
                try: session.get(site_url, timeout=10)
                except: pass

                password = generate_random_string()

                try:
                    jwt, email = email_service.create_email()
                    current_email = email
                except Exception as e:
                    with print_lock:
                        print(f"[-] 邮箱创建失败: {e}")
                    jwt, email, current_email = None, None, None

                if not email:
                    time.sleep(5)
                    continue

                if stop_event.is_set():
                    email_service.delete_email(email)
                    current_email = None
                    return

                with print_lock:
                    print(f"\n{'─'*55}")
                    print(f"  📧 开始注册: {email}")
                    print(f"{'─'*55}")

                # Step 1: 发送验证码
                log(email, "发送验证码", "info")
                ok, err = send_email_code_grpc(session, email)
                if not ok:
                    log(email, "发送验证码失败", "fail", err or "未知错误")
                    email_service.delete_email(email)
                    current_email = None
                    time.sleep(5)
                    continue
                log(email, "验证码已发送", "ok")

                # Step 2: 获取验证码
                log(email, "等待邮件验证码...", "info")
                verify_code = email_service.fetch_verification_code(email)
                if not verify_code:
                    log(email, "获取验证码失败", "fail", "邮件未到达或超时")
                    email_service.delete_email(email)
                    current_email = None
                    continue
                log(email, "验证码已获取", "ok", f"CODE: {verify_code}")

                # Step 3: 验证验证码
                log(email, "提交验证码", "info")
                ok, err = verify_email_code_grpc(session, email, verify_code)
                if not ok:
                    log(email, "验证码验证失败", "fail", err or "未知错误")
                    email_service.delete_email(email)
                    current_email = None
                    continue
                log(email, "验证码验证通过", "ok")

                # Step 4: 注册（最多重试3次）
                registered = False
                for attempt in range(3):
                    if stop_event.is_set():
                        email_service.delete_email(email)
                        current_email = None
                        return

                    log(email, f"获取 Turnstile Token（第{attempt+1}次）", "info")
                    try:
                        task_id = turnstile_service.create_task(site_url, config["site_key"])
                        token = turnstile_service.get_response(task_id)
                    except Exception as e:
                        log(email, "Turnstile 请求异常", "fail", str(e)[:80])
                        continue

                    if not token or token == "CAPTCHA_FAIL":
                        log(email, "Turnstile 验证失败", "fail", "IP被拒绝或验证码服务异常")
                        continue
                    log(email, "Turnstile Token 获取成功", "ok")

                    headers = {
                        "user-agent": account_user_agent,
                        "accept": "text/x-component",
                        "content-type": "text/plain;charset=UTF-8",
                        "origin": site_url,
                        "referer": f"{site_url}/sign-up",
                        "cookie": f"__cf_bm={session.cookies.get('__cf_bm', '')}",
                        "next-router-state-tree": config["state_tree"],
                        "next-action": final_action_id
                    }
                    payload = [{
                        "emailValidationCode": verify_code,
                        "createUserAndSessionRequest": {
                            "email": email,
                            "givenName": generate_random_name(),
                            "familyName": generate_random_name(),
                            "clearTextPassword": password,
                            "tosAcceptedVersion": "$undefined"
                        },
                        "turnstileToken": token,
                        "promptOnDuplicateEmail": True
                    }]

                    log(email, "提交注册请求", "info")
                    with post_lock:
                        try:
                            res = session.post(f"{site_url}/sign-up", json=payload, headers=headers)
                        except Exception as e:
                            log(email, "注册请求异常", "fail", str(e)[:80])
                            time.sleep(3)
                            continue

                    if res.status_code != 200:
                        log(email, "注册请求失败", "fail", f"HTTP {res.status_code}")
                        time.sleep(3)
                        continue

                    match = re.search(r'(https://[^" \s]+set-cookie\?q=[^:" \s]+)1:', res.text)
                    if not match:
                        err_match = re.search(r'"message":"([^"]+)"', res.text)
                        err_msg = err_match.group(1) if err_match else "响应无跳转链接，IP可能被封"
                        log(email, "注册被拒绝", "fail", err_msg)
                        email_service.delete_email(email)
                        current_email = None
                        registered = True
                        break

                    log(email, "注册响应正常，获取 SSO Cookie", "info")
                    verify_url = match.group(1)
                    session.get(verify_url, allow_redirects=True)
                    sso = session.cookies.get("sso")
                    sso_rw = session.cookies.get("sso-rw")

                    if not sso:
                        log(email, "SSO Cookie 获取失败", "fail", "Cookie为空")
                        email_service.delete_email(email)
                        current_email = None
                        registered = True
                        break
                    log(email, "SSO Cookie 获取成功", "ok", f"{sso[:20]}...")

                    # Step 5: TOS
                    log(email, "同意用户协议 (TOS)", "info")
                    tos_result = user_agreement_service.accept_tos_version(
                        sso=sso, sso_rw=sso_rw or "",
                        impersonate=impersonate_fingerprint, user_agent=account_user_agent,
                    )
                    if not tos_result.get("ok") or not (tos_result.get("hex_reply") or ""):
                        log(email, "TOS 同意失败", "fail", tos_result.get("error", "未知"))
                        email_service.delete_email(email)
                        current_email = None
                        registered = True
                        break
                    log(email, "TOS 同意成功", "ok")

                    # Step 6: NSFW
                    log(email, "开启 NSFW 设置", "info")
                    nsfw_result = nsfw_service.enable_nsfw(
                        sso=sso, sso_rw=sso_rw or "",
                        impersonate=impersonate_fingerprint, user_agent=account_user_agent,
                    )
                    if not nsfw_result.get("ok") or not (nsfw_result.get("hex_reply") or ""):
                        log(email, "NSFW 设置失败", "fail", nsfw_result.get("error", "未知"))
                        email_service.delete_email(email)
                        current_email = None
                        registered = True
                        break
                    log(email, "NSFW 设置成功", "ok")

                    # Step 7: Unhinged
                    log(email, "开启 Unhinged 模式", "info")
                    unhinged_result = nsfw_service.enable_unhinged(sso)
                    if unhinged_result.get("ok"):
                        log(email, "Unhinged 模式开启成功", "ok")
                    else:
                        log(email, "Unhinged 模式开启失败", "warn", "不影响账号可用性")

                    # 写入
                    with file_lock:
                        global success_count
                        if success_count >= target_count:
                            if not stop_event.is_set():
                                stop_event.set()
                            email_service.delete_email(email)
                            current_email = None
                            registered = True
                            break
                        try:
                            with open(output_file, "a") as f:
                                f.write(sso + "\n")
                        except Exception as write_err:
                            log(email, "写入文件失败", "fail", str(write_err))
                            email_service.delete_email(email)
                            current_email = None
                            registered = True
                            break

                        success_count += 1
                        avg = (time.time() - start_time) / success_count
                        with print_lock:
                            print(f"\n  🎉 注册成功 [{success_count}/{target_count}] | {email} | 平均耗时: {avg:.1f}s\n")

                        email_service.delete_email(email)
                        current_email = None
                        if success_count >= target_count and not stop_event.is_set():
                            stop_event.set()
                            with print_lock:
                                print(f"[*] 已达到目标数量 {success_count}/{target_count}，停止注册")
                        registered = True
                    break

                if not registered and current_email:
                    log(email, "3次重试全部失败，放弃此邮箱", "fail")
                    email_service.delete_email(email)
                    current_email = None
                    time.sleep(5)

        except Exception as e:
            with print_lock:
                print(f"[-] 线程异常: {str(e)[:80]}")
            if current_email:
                try: email_service.delete_email(current_email)
                except: pass
                current_email = None
            time.sleep(5)

def main():
    print("=" * 55)
    print("  Grok 批量注册机")
    print("=" * 55)

    print("[*] 正在初始化，获取 Action ID...")
    start_url = f"{site_url}/sign-up"
    with requests.Session(impersonate=DEFAULT_IMPERSONATE, proxies=get_random_proxy()) as s:
        try:
            html = s.get(start_url).text
            key_match = re.search(r'sitekey":"(0x4[a-zA-Z0-9_-]+)"', html)
            if key_match:
                config["site_key"] = key_match.group(1)
            tree_match = re.search(r'next-router-state-tree":"([^"]+)"', html)
            if tree_match:
                config["state_tree"] = tree_match.group(1)
            soup = BeautifulSoup(html, 'html.parser')
            js_urls = [urljoin(start_url, script['src']) for script in soup.find_all('script', src=True) if '_next/static' in script['src']]
            for js_url in js_urls:
                js_content = s.get(js_url).text
                match = re.search(r'7f[a-fA-F0-9]{40}', js_content)
                if match:
                    config["action_id"] = match.group(0)
                    print(f"[+] Action ID: {config['action_id']}")
                    break
        except Exception as e:
            print(f"[-] 初始化失败: {e}")
            return

    if not config["action_id"]:
        print("[-] 错误: 未找到 Action ID，请检查网络")
        return

    try:
        t = int(input("\n并发数 (默认8): ").strip() or 8)
    except:
        t = 8

    try:
        total = int(input("注册数量 (默认100): ").strip() or 100)
    except:
        total = 100

    global target_count, output_file
    target_count = max(1, total)

    from datetime import datetime
    os.makedirs("keys", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"keys/grok_{timestamp}_{target_count}.txt"

    print(f"\n[*] 启动 {t} 个线程，目标 {target_count} 个")
    print(f"[*] 输出文件: {output_file}")
    print("=" * 55)

    with concurrent.futures.ThreadPoolExecutor(max_workers=t) as executor:
        futures = [executor.submit(register_single_thread) for _ in range(t)]
        concurrent.futures.wait(futures)

    print("\n" + "=" * 55)
    print(f"  完成！成功注册 {success_count}/{target_count} 个账号")
    print(f"  输出文件: {output_file}")
    print("=" * 55)

if __name__ == "__main__":
    main()
