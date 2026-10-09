# PMSS 第十六阶段：指定项目与日期的场景约束/初始状态只读采集

## 为什么要新增这一功能

PowerBid 已经有：
- 登录态 PMSS 项目、案例和发电机列表的只读查询；
- 场景计算约束接口（POST `scene/unitParam/list`，仅查询）；
- 机组初始状态接口（GET `project/getUnitInitialStateInput`）；
- 已有 `summarize_scene_constraint_evidence` 对匿名0/1开关编码、初始状态字段覆盖和数字范围的脱敏统计；
- `attach_pmss_evidence` 将此类摘要与原来具有验证过DC网架的历史快照进行文件级摘要哈希和案例日期绑定。

之前依赖人工单独运行、保存原始响应并填写场景日期，再分别运行两个离线合并脚本。本次新增的**受控只读导出工具**可以用正确登录状态一步完成上述串接，并坚持不推测物理参数的字段单位或编码含义。

## 提交内容

- `src/powerbid/pmss_scene_evidence_export.py`：核心纯函数 `collect_same_case_scene_evidence`。显式选择 `project_id` 和 `case_date`，先检查本地脱敏历史快照日期、24小时市场映射和已存在的 `dcNetwork`，再使用合法 PMSS 会话：
  1. 调用现有 `get_context(project_id)`，核对项目ID、当前**全部机组ID集合与数量**和快照完全一致；
  2. 从对应项目案例列表中只选出唯一一个精确匹配日期的案例，缺失或同日重复均拒绝；
  3. 使用该案例真实 `pmSceneId` 和 `caseId` 调用上述两个已有只读方法；
  4. 要求接口分页完整、`rowCount` 与实际返回行数相同、两个来源都有至少1行；
  5. 对响应数据进行**匿名统计**，并按本地明确的案例日期关联成新脱敏快照，增加SHA-256文件摘要绑定。不返回或保存原始场景/机组记录。

- `scripts/export_pmss_scene_evidence.py`：可信主机专用CLI，使用**当前已有的官方网页登录状态**，不含自动登录/密码操作。只从本地权限允许的 `PMSS_COOKIE_FILE` 文件读取认证信息，该文件必须是所有者专有（如0600），不允许符号链接；输出单独的新私有JSON，严格 `0600` 和独占创建 `O_EXCL`，拒绝覆盖原快照。

- `tests/test_pmss_scene_evidence_export.py`：使用纯合成适配器独立验证唯一日期+项目+全部机组身份匹配、仅调用允许的只读路由、分页截断拒绝、空数据拒绝、同日歧义拒绝、登陆失效不输出、文件0600和不覆盖、认证字段不会回显。测试完全没有向真实老师 PMSS 发起请求。

## 使用方式

只有在官方PMSS登录可用、明确知道项目ID、并持有**同一案例**的带 `dcNetwork` 脱敏历史快照时，才能在已授权的可信服务器上执行：

```bash
export PMSS_BASE_URL='https://<your-authorized-school-PMSS-host>'
export PMSS_PROXY_URL='socks5h://127.0.0.1:11080'  # 只有学校网络需要时
export PMSS_COOKIE_FILE='/private/pmss-cookie.json'  # 文件需0600，不能传入Git

python scripts/export_pmss_scene_evidence.py \
  --snapshot /private/pmss-case-2025-09-01.json \
  --project-id '<authorized-project-id>' \
  --case-date 2025-09-01 \
  --output /private/pmss-case-2025-09-01-scene-bound.json
```

输出文件必须事先不存在。程序绝不会覆盖源文件、抓取未授权案例、提交报价或执行老师平台出清。

若返回HTTP 200但业务结果为 `T000`，脚本返回状态码3且不输出文件，提示从学校官方界面重新认证；VPN可连接不代表PMSS应用已登录。其他缺少权限、项目不匹配、分页不完整或数据异常返回状态码4且不会回显原始错误响应或cookie。

## 为什么仍然不能直接运行真实SCUC

匿名只读来源可以建立“当前项目/日期/机组身份在查询时一致”的流程级证明，以及新匿名摘要与文件的完整性绑定，但这仍不是老师平台的**加密签名/源数据库认证**。场景约束0/1编码没有经过课程语义确认，`incRate`等字段时间单位及启动爬坡、停机成本仍缺完整证据，不能把匿名统计直接映射为机组 `ThermalConstraints`。

所有生成的 `evidenceBinding.independentlyVerified=false`、研究界面`teacher_platform_source_authenticated=false`和`model_technical_parameters_verified=false`仍保持现有逻辑；联合24小时真实机组研究的逐值课程出处门槛不会降低。

## 2026-10-09 验收边界

当前编程会话的服务器未提供可验证的 `PMSS_BASE_URL` 和 `PMSS_COOKIE_FILE` 运行配置，也没有通过本CLI读取实际 PMSS 案例；此前的实际登录诊断出现过 `T000`。因此本阶段交付的是**经过完整合成测试的授权只读采集流程**，不宣称2025-09-01的实际场景资料已经补齐、生产网页已部署或平台物理模型已获独立认证。

不应为了赶进度绕过受 `root:root 0600` 保护的既有场景/技术资料，也不应将真实原始结果、Cookie、Token、案例标识及非脱敏网架提交公共仓库。

后续：在有权限的官方登录会话建立后，使用本CLI获取最小必要的同案例匿名场景摘要，再逐项核对单位、语义与设备对应关系；取得多个独立历史日期后再检验联合模型。
