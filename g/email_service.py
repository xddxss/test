"""邮箱服务类 - 适配 freemail API"""
import os
import time
import requests
from dotenv import load_dotenv


class EmailService:
    def __init__(self):
        load_dotenv()
        self.worker_domain = os.getenv("WORKER_DOMAIN")
        self.freemail_token = os.getenv("FREEMAIL_TOKEN")
        if not all([self.worker_domain, self.freemail_token]):
            raise ValueError("Missing: WORKER_DOMAIN or FREEMAIL_TOKEN")
        self.base_url = f"https://{self.worker_domain}"
        self.headers = {"Authorization": f"Bearer {self.freemail_token}"}

    def create_email(self):
        """创建临时邮箱 GET /api/generate"""
        try:
            res = requests.get(
                f"{self.base_url}/api/generate",
                headers=self.headers,
                timeout=10
            )
            if res.status_code == 200:
                email = res.json().get("email")
                return email, email  # 兼容原接口 (jwt, email)
            print(f"[-] 创建邮箱失败: {res.status_code} - {res.text}")
            return None, None
        except Exception as e:
            print(f"[-] 创建邮箱失败: {e}")
            return None, None

    def fetch_verification_code(self, email, max_attempts=30):
        """轮询获取验证码 GET /api/emails?mailbox=xxx"""
        for _ in range(max_attempts):
            try:
                res = requests.get(
                    f"{self.base_url}/api/emails",
                    params={"mailbox": email},
                    headers=self.headers,
                    timeout=10
                )
                if res.status_code == 200:
                    emails = res.json()
                    if emails and emails[0].get("verification_code"):
                        code = emails[0]["verification_code"]
                        return code.replace("-", "")
            except:
                pass
            time.sleep(1)
        return None

    def delete_email(self, address):
        """删除邮箱 DELETE /api/mailboxes?address=xxx"""
        try:
            res = requests.delete(
                f"{self.base_url}/api/mailboxes",
                params={"address": address},
                headers=self.headers,
                timeout=10
            )
            return res.status_code == 200 and res.json().get("success")
        except:
            return False
