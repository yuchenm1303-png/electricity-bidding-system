# PMSS EasyConnect / SOCKS5 私网链路诊断

## 2026-10-08 实测状态（可信服务器）

- `powerbid-easyconnect` 容器、SOCKS5监听和服务器公网正常，`https://example.com` 经过本地 `127.0.0.1:11080` 代理返回 HTTP 200。
- 老师 PMSS 课程站点属于私网地址。同一代理访问其只读首页无法建立TCP连接，直连也超时；浏览器内只读项目查询报 `Failed to fetch`。
- EasyConnect 容器当前仅见普通Docker `eth0` 和 `lo`，没有核实到正在工作的VPN隧道网卡。**这足以表明当前不能证明校园内网连通，但不能单凭缺少tun设备确定根因**。
- 账号/会话是否失效、网关和校内私网路由是否改变尚未核实。不能声称当前已登录成功，也不能在未知状态下盲目重试报价保存或触发真实出清。

## 新增安全诊断工具

`scripts/diagnose_pmss_connectivity.py` 只运行HEAD，不跟随重定向，不使用 Cookie/Token，不读取任何PMSS数据表、不执行POST。对公网测试站点和指定私网PMSS网页，分别经本地SOCKS5及直连测试HTTP传输层。请求可能返回401/403，但它们只代表目标服务器可达，不代表用户已授权登录。

服务器上运行（由运维提供当地授权的 **URL中不含凭据/查询参数** 的PMSS只读网页）：

```sh
python scripts/diagnose_pmss_connectivity.py \
  --target-url "http://<PMSS授权站点>/pmss/main.html" \
  --proxy socks5h://127.0.0.1:11080 \
  --timeout 7
```

输出只含诊断状态、HTTP状态、curl错误类别以及处理建议，**不回显域名/IP/URL/Cookie/Token/响应正文/跳转地址**。返回码0只表示私网HTTP传输可达；返回码2表示链路仍有故障。遇到某一路由超时不会把“代理端口可访问”错误认定为“校园VPN已连接”。

状态区分：

- `LOCAL_PROXY_UNAVAILABLE`：本地SOCKS监听缺失
- `PROXY_UPSTREAM_UNAVAILABLE`：SOCKS无法连公网，可能是代理/EasyConnect上游中断
- `PUBLIC_PROXY_OK_PRIVATE_TARGET_UNREACHABLE`：SOCKS访问公网正常，但PMSS私网不可达，优先核查EasyConnect会话、校园网关、私网路由或访问策略
- `PRIVATE_ENDPOINT_REACHABLE`：私网网页已有HTTP回应；仍需进一步只读核实账号及课程数据权限
- `HOST_PUBLIC_CONNECTIVITY_UNAVAILABLE`：先解决服务器基础公网问题

脚本不读取原始私有快照，也没有修改老师平台。恢复连接之后使用已有 `TeacherPlatformAdapter.get_scene_unit_constraints` 与 `get_unit_initial_state_inputs` 做同一案例的真实只读检查；必须通过原始字段含义、时间单位、机组ID对应关系核实，才讨论联合24小时模型可用性。

严禁把诊断成功直接当成“市场出清模型验证通过”。
