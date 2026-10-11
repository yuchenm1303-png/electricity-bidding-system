# PMSS / EasyConnect 连接管理中心

这是 PowerBid 自己的管理员操作面板，不嵌入学校登录页，也不把学校账号密码带进网页。

## 工作流程

1. 仅 PowerBid 已登录管理员在「PMSS 市场分析」看到连接中心。
2. `GET /api/pmss/connection/status` 返回：VPN 容器是否运行、PMSS 只读查询授权是否有效、快照目录是否已经配置。PMSS 授权通过的是 **只读 project/list 的 T200**；EasyConnect 容器在运行或旧 Cookie 存在，均 **不足以证明 VPN 已连接**。状态探针带有限时缓存，避免频繁访问老师服务。
3. `POST /api/pmss/connection/reconnect` 需要管理员账号 + 原有 X-PowerBid-Request CSRF 标记，经 **Unix 套接字** 发送固定 `POST /reconnect`。主服务不装 Docker CLI，也不挂 Docker socket。
4. 受限 operator 唯一允许重启的容器固定是 `powerbid-easyconnect`；重启冷却 180 秒。按钮先确认，不会自动调用学校 PMSS 写入接口或自动出清。
5. 若学校要求二次登录或验证码，管理员必须完成原本的受控认证。外部“学校登录门户”链接只登录本机浏览器，**不等于服务器 VPN 已重新认证**。当前没有做浏览器内远程桌面/WebVNC，不要误称一键重连解决所有验证码。
6. VPN 恢复后，PMSS 的私有案例标准导入仍需通过现有授权只读流程进行；网页的快照目录不会凭空出现。

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

生产需验收：管理员可见、普通用户不可见，匿名/普通账号获取状态和重启分别 401/403；重启返回不宣称已登录；冷却可用；服务异常不影响 PowerBid 主站和其他容器。生产重连前先保证学校授权及维护窗口，避免中断其他使用同一 VPN 的教学任务。
