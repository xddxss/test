"""
Turnstile验证服务类
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()


class TurnstileService:
    """Turnstile验证服务类"""

    def __init__(self, solver_url="http://127.0.0.1:5072"):
        """
        初始化Turnstile服务
        """
        self.yescaptcha_key = os.getenv('YESCAPTCHA_KEY', '').strip()
        self.solver_url = solver_url
        self.yescaptcha_api = "https://api.yescaptcha.com"

    def create_task(self, siteurl, sitekey):
        """
        创建Turnstile验证任务
        """
        if self.yescaptcha_key:
            # 使用 YesCaptcha API
            url = f"{self.yescaptcha_api}/createTask"
            payload = {
                "clientKey": self.yescaptcha_key,
                "task": {
                    "type": "TurnstileTaskProxyless",
                    "websiteURL": siteurl,
                    "websiteKey": sitekey
                }
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get('errorId') != 0:
                raise Exception(f"YesCaptcha创建任务失败: {data.get('errorDescription')}")
            return data['taskId']
        else:
            # 使用本地 Turnstile Solver
            url = f"{self.solver_url}/turnstile?url={siteurl}&sitekey={sitekey}"
            response = requests.get(url)
            response.raise_for_status()
            return response.json()['taskId']

    def get_response(self, task_id, max_retries=30, initial_delay=5, retry_delay=2):
        """
        获取Turnstile验证响应
        """
        time.sleep(initial_delay)

        for _ in range(max_retries):
            try:
                if self.yescaptcha_key:
                    # 使用 YesCaptcha API
                    url = f"{self.yescaptcha_api}/getTaskResult"
                    payload = {
                        "clientKey": self.yescaptcha_key,
                        "taskId": task_id
                    }
                    response = requests.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()

                    if data.get('errorId') != 0:
                        print(f"YesCaptcha获取结果失败: {data.get('errorDescription')}")
                        return None

                    if data.get('status') == 'ready':
                        token = data.get('solution', {}).get('token')
                        if token:
                            return token
                        else:
                            print("YesCaptcha返回结果中没有token")
                            return None
                    elif data.get('status') == 'processing':
                        time.sleep(retry_delay)
                    else:
                        print(f"YesCaptcha未知状态: {data.get('status')}")
                        time.sleep(retry_delay)
                else:
                    # 使用本地 Turnstile Solver
                    url = f"{self.solver_url}/result?id={task_id}"
                    response = requests.get(url)
                    response.raise_for_status()
                    data = response.json()
                    captcha = data.get('solution', {}).get('token', None)

                    if captcha:
                        if captcha != "CAPTCHA_FAIL":
                            return captcha
                        else:
                            return None
                    else:
                        time.sleep(retry_delay)
            except Exception as e:
                print(f"获取Turnstile响应异常: {e}")
                time.sleep(retry_delay)

        return None
