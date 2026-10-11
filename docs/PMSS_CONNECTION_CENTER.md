# PMSS / EasyConnect 连接管理中心

这是 PowerBid 面向**所有已登录账号（管理员和普通成员）**的共享服务器连接面板，不嵌入学校登录页，也不把学校账号密码带进网页。

## 工作流程

1. PowerBid 的所有已登录用户都能在「PMSS 市场分析」看到连接中心，匿名用户仍被 401 拒绝。连接状态反映**服务器共享通道**，不代表使用者拥有学校 PMSS 的个人数据授权。
2. `GET /api/pmss/connection/status` 返回：VPN 容器是否运行、PMSS 只读查询授权是否有效、快照目录是否已经配置。PMSS 授权通过的是 **只读 project/list 的 T200**；EasyConnect 容器在运行或旧 Cookie 存在，均 **不足以证明 VPN 已连接**。状态探针带有限时缓存，避免频繁访问老师服务。
3. `POST /api/pmss/connection/reconnect` 对所有**已登录 PowerBid 用户**开放，仍要求原有 X-PowerBid-Request CSRF 标记，且不能携带任意参数；仅在只读 PMSS 状态探针确认 `unreachable` 时允许执行。`authorized` 状态返回 409 以避免打断其他用户；`login_required` 返回 409 提醒重新认证；`unknown` 失败关闭。由 **Unix 套接字**发送固定的 `POST /reconnect`，主服务不装 Docker CLI，也不挂 Docker socket。
4. 受限 operator 唯一允许重启的容器固定是 `powerbid-easyconnect`；全局重启冷却 180 秒，在这个冷却期内所有账号都无法再次重启。按钮先提示这是**共享 VPN**，不会自动调用学校 PMSS 写入接口或自动出清。
5. 若学校要求二次登录或验证码，具有学校授权的使用者仍必须完成原本的受控认证。外部“学校登录门户”链接只登录本机浏览器，**不等于服务器 VPN 已重新认证**。当前没有做浏览器内远程桌面/WebVNC，不要误称一键重连解决所有验证码。
6. VPN 恢复后，PMSS 的私有案例标准导入仍需通过现有授权只读流程进行；网页的快照目录不会凭空出现。**不要把已有的管理员私有课程快照直接向所有普通账户开放**；个人工程授权需要另外验证或明确获得学校的共享许可。

## 专用服务的权限隔离

`Dockerfile.pmss-operator` 镜像只启动 `ops/pmss_vpn_operator.py`。推荐以如下方式运行：

- `--network none`、`--read-only`、`--cap-drop ALL`、`--security-opt no-new-privileges`、`--pids-limit 40`
- 仅 operator 容器能挂载宿主机的 `/var/run/docker.sock`；**禁止**把它挂载到公网应用容器
- 宿主机 socket 目录仅专用管理员持有 `0700`，Unix socket 设 `0600`；PowerBid 通过只读目录挂载使用这个 socket，不对公网提供 TCP 或 WebSocket 管理端口
- Docker 操作器使用固定 API 路径 `/containers/powerbid-easyconnect/{json,restart}`，不接受容器名、shell 命令、外部地址、凭据等用户输入
- operator Docker socket 在宿主机相当于高权限。务必只允许可信构建镜像运行，不向任何其他业务容器或用户共享；如不满足隔离条件应保持重连按钮禁用

## 新增配置

Web app:
`/run/powerbid-vpn/vpn.sock` 必须由 operator 通过**只读 Unix-socket 目录挂载**提供。
私有历史案例保留 `/private/powerbid-pmss` 只读挂载。
无 operator 时 status 接口返回 `operator=unavailable`，POST 返回 503，UI 禁止点击，不执行伪重连。

## 测试

`ruff check . && pytest -q tests/test_pmss_connection_api.py && (cd frontend && npm ci && npm run build)`

生产需验收：管理员和普通登录账号都能查看共享状态；匿名访问仍 401；普通账号在 PMSS 已授权或需要登录时不能重启；确认连接不可达后才允许重启；重启请求不得包含任意命令或容器名；冷却期有效；服务异常不影响 PowerBid 主站和其他容器。服务器共享会话与个人 PMSS 工程访问权限分离；不得向无学校授权的用户泄露老师平台的受保护数据。
