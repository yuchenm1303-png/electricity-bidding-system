# 第十七阶段：PMSS 应用登录只读预检与认证防泄漏加固

## 实际排查结论

2026-10-09，可信服务器开发会话中 `PMSS_BASE_URL`、`PMSS_COOKIE_FILE`、`PMSS_PROJECT_ID` 和 `PMSS_PROXY_URL` 均**没有配置**；因此，当前无法开展真实 PMSS 同案例读取，也不能据此推断学校 VPN 已坏或老师账号密码不对。

现在可以通过一个专用的**只读登录预检脚本**明确区分“还没配置”“应用登录失效”“服务端重定向”“指定项目无权限”“日期不存在或有歧义”与“指定项目/日期的 GET 可读”。

## 直接使用

仅在已有合法学校 PMSS 账号、已通过官方网页登录，且有权读取项目时，才应在可信服务器设置：

```bash
export PMSS_BASE_URL='https://<official-school-pmss-origin>'
export PMSS_COOKIE_FILE='/private/authorized-pmss-cookies.json'
# 校园网络有需要时，显式指定本机 SOCKS5h 代理：
export PMSS_PROXY_URL='socks5h://127.0.0.1:11080'

python scripts/doctor_pmss_session.py \
  --project-id '<exact-authorized-project-id>' \
  --case-date 2025-09-01
```

认证 Cookie 文件必须是**仅文件所有者可读**的 JSON Cookie 名称和值字典，不能是符号链接，且不可上传 GitHub、贴到聊天或写进代码。网页登录授权和 Cookie 的持有及保管均由合法操作人员完成；脚本不尝试自动输入密码或绕过官方认证。

本脚本最多执行**分页有上限的项目列表 GET**，并且只有指定项目匹配后，才会额外执行案例列表 GET；没有发电机报价保存、仿真执行、清算或其他市场写操作。

### 状态码（不会打印网站地址、项目 ID 或 Cookie）

| 退出码 | 状态 | 解释 |
|---:|---|---|
| 0 | PMSS_SESSION_AND_CASE_READABLE | 当前会话能够读取指定项目和唯一匹配的案例日期，但还没有核实当前案例的全部机组身份与场景数据 |
| 0 | PMSS_SESSION_PROJECT_READABLE | 只要求项目时的只读校验通过，未检查日期 |
| 2 | NOT_CONFIGURED | 缺少必要服务器配置；**不能推断 VPN 或账户状态** |
| 3 | PMSS_APP_LOGIN_EXPIRED | PMSS 业务层明确返回 T000 |
| 4 | REDIRECT_BLOCKED_LOGIN_UNVERIFIED | 服务器发出跳转，但无法证明有效登录；为防 Cookie 泄漏没有跟随跳转 |
| 5 | AUTH_OR_PROJECT_UNVERIFIED / CASE_QUERY_UNAVAILABLE | 网络、权限或列表查询无法验证 |
| 6 | CASE_DATE_MISSING_OR_AMBIGUOUS | 所选项目在指定日期没有唯一案例 |
| 7 | INVALID_LOCAL_CONFIGURATION | 网址、代理、Cookie 文件权限、项目/日期参数不符合基本安全要求 |

后续真正的匿名场景摘要提取，仍通过上阶段的：

```bash
python scripts/export_pmss_scene_evidence.py \
  --snapshot /private/pmss-case-2025-09-01.json \
  --project-id '<exact-authorized-project-id>' \
  --case-date 2025-09-01 \
  --output /private/pmss-case-2025-09-01-scene-bound.json
```

输出必须是尚未存在的新私有文件（0600），真实PMSS案例仍需机组 ID 完整核对、完整分页和只读场景数据校验。

## 客户端安全修复

`src/powerbid/adapters/teacher_platform.py`：
- 校验明确的 HTTP(S) PMSS 基础地址，拒绝地址内凭据、查询参数、片段和歧义 URL；
- 禁止 HTTP 自动跟随 30x 重定向，尤其避免 Cookie 被 SSO/第三方登录跳转带往其他站点；不打印 Location；
- 401/403 或其他4xx不会无限重复 GET 或误认成功；
- 原本非 JSON 响应错误会包含真实 `response.text[:300]`，现在只返回不含服务器正文的类别说明；
- 原本服务端 `retMsg` 会进入报错，现只输出经过严格格式检查的短 `retCode`；
- 网络错误不输出原始 HTTP 地址、查询参数或可能包含私密信息的异常详情；
- 客户端不隐式继承进程级代理环境变量，学校 VPN 代理必须明确给出；
- 指定项目的查询增加有上限的项目列表分页（最多10页、每页50个），避免恰好不在第一页时被误判为不存在。

**注意：** 使用私有、经官方授权的 Cookie 是为了只读查询，并不证明课程运行参数的物理语义、老师PMSS定价/收益模型或自动出清已经校准。

## 安全与测试边界

- 全部开发测试使用合成 PMSS 响应和假的会话，不读取私人 Cookie，也不会向学校平台发出写操作；
- 检查会拒绝重定向、错误报文中的敏感文本、非法远程代理、权限过宽的 Cookie 文件、没有精确匹配的项目；
- 当前真实服务器上预检返回 `NOT_CONFIGURED`，**没有成功读取新的真实 PMSS 项目或历史场景**；
- 本阶段不改报价策略、1001未证实价格上限、真实平台收益，也不修改 React 工作台。

获取明确授权的官方PMSS会话后，先预检指定项目/日期，再尝试同案例只读导出；没有官方登录态不能偷偷尝试字典密码或绕过原本的 root 私有文件权限。
