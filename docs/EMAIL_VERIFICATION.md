# PowerBid 六位邮箱验证码

实现：注册时向目标邮箱发送六位数字验证码，十分钟过期且只能使用一次。验证码以独立 pepper 的 HMAC-SHA256 摘要保存。验证及创建用户在单次 SQLite 事务中完成。失败尝试最多五次，同地址发送冷却 60 秒，附带按地址、客户端与全局的发送频率限制。

邮件服务：Resend API，须有经过验证的域名与具有发信权限的密钥。生产环境需要三个凭据及开关：

    POWERBID_EMAIL_VERIFICATION_ENABLED=1
    POWERBID_RESEND_API_KEY=发送权限 API key
    POWERBID_EMAIL_FROM=PowerBid <account@smirel.com>
    POWERBID_EMAIL_CODE_SECRET=独立的随机秘密值

只在 root-only 的服务器配置文件中管理私钥，并通过容器环境注入，不得上传仓库、聊天、静态站点或者 CI 日志。

重要：2026-10-09 测试复用 Loom 的现有 Resend 发送通道，使用官方模拟测试收件地址尝试发信，返回 HTTP 403。发送服务验证成功之前，正式网站不能开启强制邮箱验证码，否则会阻止新用户注册。先检查 Resend 域名验证及发信 API Key 权限，修复后再用官方 delivered@resend.dev 模拟收件地址测试成功。

POWERBID_EMAIL_VERIFICATION_ENABLED=0 时，新邮箱验证码接口返回未开放，原注册登录继续正常运行；不会更改现有管理员、用户、登录会话。

设计要点：
- 验证码必须在服务端校验。
- 配置不完整时不允许绕过强制验证。
- 数据继续使用既有持久化用户数据库。
- 发送失败自动撤销未发送成功的验证码。
- 若启用 Cloudflare Turnstile，发送验证码时也执行 Turnstile 服务端验证。
- 已注册邮箱返回不暴露账号状态的通用提示。
