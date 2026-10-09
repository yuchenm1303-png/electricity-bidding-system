# PowerBid 验证码与第三方快捷登录

状态：功能已开发；正式 OAuth/Turnstile 密钥缺失时继续关闭相应入口，不影响现有管理员账号和密码登录。

## Cloudflare Turnstile

在 Cloudflare 控制台新建 Turnstile widget，允许 hostname power.smirel.com，取得 Site Key 和 Secret Key。生产容器增加：

    POWERBID_TURNSTILE_SITE_KEY=公开站点密钥
    POWERBID_TURNSTILE_SECRET_KEY=私密验证密钥
    POWERBID_TURNSTILE_HOSTNAME=power.smirel.com

启用后登录和注册都需要完成人机验证。服务端发送 token 到 Cloudflare Siteverify，检查 success 和 hostname。过期、重复、伪造或不匹配时拒绝请求；部分密钥缺失时拒绝验证，而非允许绕过。

## Google OAuth

在 Google Cloud Console 创建 Web OAuth 2.0 Client，回调 URI 为：

    https://power.smirel.com/api/auth/oauth/google/callback

设置 Google OAuth consent screen 和测试用户或正式发布，然后通过私密服务端配置设置：

    POWERBID_GOOGLE_CLIENT_ID=Google Client ID
    POWERBID_GOOGLE_CLIENT_SECRET=Google Client Secret

Google 授权 scopes：openid email profile。后端检查 Google ID Token 的签名、有效期、受众、发行者和 verified_email。

## GitHub OAuth

在 GitHub Developer Settings 创建 OAuth App：
Homepage URL: https://power.smirel.com/
Authorization callback URL:

    https://power.smirel.com/api/auth/oauth/github/callback

配置：

    POWERBID_GITHUB_CLIENT_ID=GitHub Client ID
    POWERBID_GITHUB_CLIENT_SECRET=GitHub Client Secret

后端使用 GitHub 用户唯一 ID 和经过验证的邮箱关联用户，授权 scope 为 read:user user:email。

## 安全保证与当前限制

1. OAuth 使用短期一次性随机 state，服务器保存摘要，浏览器用 HttpOnly、Secure、SameSite=Lax cookie 匹配。回调不支持外部任意 redirect。
2. 即使第三方邮箱与现有账号相同，也绝不隐式合并或升级角色。现有账号需使用密码登录，未来另外设计需二次认证的显式关联。
3. 注册的新用户始终为 member，遵循公开注册开关；已绑定的第三方账号可再次登录。
4. 未配置 OAuth 时界面显示待配置而非虚假的可用按钮；不配置 Turnstile 时密码登录与注册保持旧版行为。
5. 所有私密密钥仅存服务器安全配置，绝不提交 GitHub、复制到日志、截图或聊天。
6. 本阶段是人机验证码，不是邮件 OTP。邮箱验证、密码找回和账号绑定可在下一阶段完成。

## 部署

使用现有生产数据卷 /srv/powerbid-accounts；部署候选容器后先跑健康、登录 UI、公开配置、匿名 API 返回 401 等检查。保留旧生产容器用于回滚。

配置查询 GET /api/auth/config 仅返回开关以及公开 Site Key，不返回任何 private secret。
