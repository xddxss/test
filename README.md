# Grok 批量注册机

基于 [muqing-kg/grokzhuce](https://github.com/muqing-kg/grokzhuce) 二次修改，优化了注册流程日志输出，并完善了 Cloudflare freemail 后端部署文档。

---

## 功能特性

- 自动创建临时邮箱、接收验证码、完成注册
- 自动同意用户协议（TOS）+ 开启 NSFW
- 支持 YesCaptcha 或本地 Turnstile Solver 解验证码
- 详细的每步注册流程日志输出
- 多线程并发注册

---

## 运行环境要求

- **Python 3.9+**
- **家庭宽带（住宅 IP）**，数据中心 IP 会被 x.ai 封锁
- Cloudflare 账号（免费）
- YesCaptcha 账号（新用户有免费额度）或本地 Turnstile Solver

---

## 第一步：部署 Cloudflare freemail 后端

freemail 后端负责创建临时邮箱和接收验证码，完全免费部署在 Cloudflare 上。

### 1.1 创建 D1 数据库

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com)
2. 左侧菜单 → **Workers & Pages** → **D1 SQL Database** → **Create**
3. 数据库名填写 `temp-email-db`，点击 Create
4. 进入数据库页面，点击 **Console** 标签页，执行以下 SQL：

```sql
CREATE TABLE IF NOT EXISTS mail_boxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox TEXT NOT NULL,
    subject TEXT,
    from_address TEXT,
    body TEXT,
    verification_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 1.2 创建 Worker

1. 左侧菜单 → **Workers & Pages** → **Create** → **Start with Hello World!**
2. 名称填写 `temp-email-worker`，点击 Deploy
3. 点击 **Edit Code**，全选删除默认代码，粘贴下方 Worker 代码，点击 **Deploy**

<details>
<summary>Worker 完整代码（点击展开）</summary>

```javascript
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const auth = request.headers.get('Authorization');
    if (!auth || !auth.startsWith('Bearer ')) return json({ error: 'Unauthorized' }, 401);
    const token = auth.slice(7);
    if (token !== env.FREEMAIL_TOKEN) return json({ error: 'Unauthorized' }, 401);
    if (request.method === 'GET' && url.pathname === '/api/generate') return handleGenerate(env);
    if (request.method === 'GET' && url.pathname === '/api/emails') return handleEmails(url, env);
    if (request.method === 'DELETE' && url.pathname === '/api/mailboxes') return handleDelete(url, env);
    return json({ error: 'Not Found' }, 404);
  },
  async email(message, env) {
    const to = message.to;
    const from = message.from;
    const reader = message.raw.getReader();
    const chunks = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
    }
    const totalLength = chunks.reduce((sum, c) => sum + c.length, 0);
    const merged = new Uint8Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) { merged.set(chunk, offset); offset += chunk.length; }
    const body = new TextDecoder().decode(merged);
    const subjectMatch = body.match(/^Subject:\s*(.+)$/mi);
    const subject = subjectMatch ? subjectMatch[1].trim() : '';
    const subjectCodeMatch = subject.match(/\b([A-Z0-9]{3}-[A-Z0-9]{3,})\b/);
    const bodyCodeMatch = body.match(/\b([A-Z0-9]{3}-[A-Z0-9]{3,})\b/);
    const rawCode = subjectCodeMatch ? subjectCodeMatch[1] : (bodyCodeMatch ? bodyCodeMatch[1] : null);
    const code = rawCode ? rawCode.replace('-', '') : null;
    await env.DB.prepare(
      'INSERT INTO mails (mailbox, subject, from_address, body, verification_code) VALUES (?, ?, ?, ?, ?)'
    ).bind(to, subject, from, body.substring(0, 2000), code).run();
  }
};

async function handleGenerate(env) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let name = '';
  for (let i = 0; i < 10; i++) name += chars[Math.floor(Math.random() * chars.length)];
  const address = `${name}@${env.DOMAIN}`;
  await env.DB.prepare('INSERT OR IGNORE INTO mail_boxes (address) VALUES (?)').bind(address).run();
  return json({ email: address });
}

async function handleEmails(url, env) {
  const mailbox = url.searchParams.get('mailbox');
  if (!mailbox) return json({ error: 'mailbox required' }, 400);
  const result = await env.DB.prepare(
    'SELECT * FROM mails WHERE mailbox = ? ORDER BY created_at DESC LIMIT 10'
  ).bind(mailbox).all();
  return json(result.results || []);
}

async function handleDelete(url, env) {
  const address = url.searchParams.get('address');
  if (!address) return json({ error: 'address required' }, 400);
  await env.DB.prepare('DELETE FROM mails WHERE mailbox = ?').bind(address).run();
  await env.DB.prepare('DELETE FROM mail_boxes WHERE address = ?').bind(address).run();
  return json({ success: true });
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' }
  });
}
```

</details>

### 1.3 绑定 D1 数据库

1. 进入 `temp-email-worker` → **Settings** → **Bindings** → **Add**
2. 选择 **D1 Database**
3. Variable name 填 `DB`，Database 选择 `temp-email-db`，点击 Save

### 1.4 设置环境变量

在 Settings → **Variables and Secrets** 添加两个 Secret：

| Variable name | Value |
|---|---|
| `FREEMAIL_TOKEN` | 自定义密码（记住，后面要填入 .env） |
| `DOMAIN` | 你的域名，如 `example.com` |

### 1.5 开启 Email Routing

1. 左侧菜单 → **Websites** → 进入你的域名
2. 左侧 → **Email** → **Email Routing** → **Enable Email Routing**
3. 进入 **Routing Rules** 标签页 → **Catch-all address** → **Edit**
4. Action 选择 **Send to a Worker**，Worker 选择 `temp-email-worker`，Save

---

## 第二步：配置本地运行环境

### 2.1 安装依赖

```bash
git clone https://github.com/你的用户名/你的仓库名.git
cd 你的仓库名

pip install -r requirements.txt
pip install quart camoufox rich patchright
python -m patchright install chromium
```

### 2.2 配置 .env

复制配置模板并填写：

```bash
copy .env.example .env
```

编辑 `.env`：

```env
# Worker 域名（在 Cloudflare Workers & Pages 概览页可以找到）
WORKER_DOMAIN=temp-email-worker.你的账号名.workers.dev

# 1.4 步骤中设置的 FREEMAIL_TOKEN
FREEMAIL_TOKEN=你设置的密码

# YesCaptcha API Key（https://yescaptcha.com 注册获取）
YESCAPTCHA_KEY=你的Key
```

> **注意：** 配置了 `YESCAPTCHA_KEY` 后无需启动 `api_solver.py`

---

## 第三步：运行

```bash
python grok.py
```

按提示输入并发数和注册数量，建议先用 `1` 并发、`3` 数量测试。

注册成功的 SSO Token 保存在 `keys/` 目录下。

### 运行输出示例

```
─────────────────────────────────────────────────
  📧 开始注册: abc123@example.com
─────────────────────────────────────────────────
[10:23:01]   · [abc123] 发送验证码
[10:23:02]   ✓ [abc123] 验证码已发送
[10:23:05]   · [abc123] 等待邮件验证码...
[10:23:08]   ✓ [abc123] 验证码已获取  →  CODE: M91U22
[10:23:08]   · [abc123] 提交验证码
[10:23:09]   ✓ [abc123] 验证码验证通过
[10:23:09]   · [abc123] 获取 Turnstile Token（第1次）
[10:23:15]   ✓ [abc123] Turnstile Token 获取成功
[10:23:15]   · [abc123] 提交注册请求
[10:23:16]   ✓ [abc123] SSO Cookie 获取成功
[10:23:17]   ✓ [abc123] TOS 同意成功
[10:23:18]   ✓ [abc123] NSFW 设置成功
[10:23:19]   ✓ [abc123] Unhinged 模式开启成功

  🎉 注册成功 [1/10] | abc123@example.com | 平均耗时: 18.3s
```

---

## 常见问题

| 问题 | 原因 | 解决方案 |
|---|---|---|
| `CAPTCHA_FAIL` | IP 被 Cloudflare 拒绝 | 必须使用家庭宽带，不能用数据中心服务器 |
| 注册被拒绝，响应无跳转链接 | x.ai 封锁了当前 IP | 换家庭宽带网络运行 |
| 获取验证码超时 | 邮件未到达 D1 | 检查 Email Routing Catch-all 是否指向 Worker |
| `ModuleNotFoundError` | 依赖未安装 | 重新执行 pip install 命令 |
| Action ID 未找到 | 网络不通 | 检查网络，确保能访问 accounts.x.ai |

---

## 注意事项

- 必须在**家庭宽带**环境下运行，数据中心/VPS 的 IP 会被封锁
- YesCaptcha 余额不足时注册会失败，注意充值
- 建议并发数设置 2-5，过高可能触发频率限制

---

## License

MIT
