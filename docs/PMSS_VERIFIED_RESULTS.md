# PMSS 真实结果验收记录（2026-10-08）

## 真实环境只读校验

课程场景：2025-09-01，日前市场，24 时段，10机39节点系统。

按 PMSS 前端真实逻辑操作：三个结果选择树叶子 key 带有市场前缀 `DA-` / `RT-`，而结果 POST 的 `daIds` / `rtIds` 必须传移除该前缀后的 ID。不可将机组树的元素 ID 混用到节点和支路结果。

已完成三个 Tab 的完整日前批量只读调用，响应均为 `T200`：

| 数据模块 | 选中数 | 返回数 | 24 时段字段 |
| --- | ---: | ---: | --- |
| 机组中标 | 10 | 10 | power、price、income |
| 节点电价 | 39 | 39 | powerFlow |
| 支路潮流 | 46 | 46 | powerFlow、beginNodePrice、endNodePrice、shadowPrice、blockSurplus |

注意：节点电价的 JSON 字段恰好命名为 `powerFlow`，以实际节点电价页面为准。全部上述曲线的 `datas` 为24个数值。

## 实际数据校验

已从服务器上的获授权 PMSS 会话构建脱敏只读快照：

`/tmp/powerbid_pmss_readonly_2025-09-01.json`

- 10台机组、各自历史报价曲线和成本字段
- 当天24时段的历史发电量序列
- 10条机组结果、39条节点结果、46条支路结果
- 文件权限0600；没有输出账号、密码、Cookie、Token

服务器本地运行 `snapshot_from_pmss`、`parse_nodal_prices`、`parse_branch_flows` 与 `optimize_segmented_bid`，真实输入解析成功，本地五段报价试算成功。

该快照中 `demandForecastMw` 明确使用历史已出清总发电量作为回测代理值，且 `historicalBacktestOnly=true`；它既不是真实未来预测，也不一定等于电网实际负荷。此模式只用于验证程序链路和比较假设策略。

## 软件边界与安全要求

PowerBid 提供本地单区域五段价格-电量曲线优化；其模拟价格、利润及中标量不是 PMSS 的真实网络重算结果。目前页面可以导入脱敏快照并分别查看真实已出清的机组、节点和支路记录。

没有执行真实报价保存，没有触发老师平台市场出清。保留 `save_unit_bid(..., commit=False)`、`run_clearing(..., commit=False)` 默认保护。未经另行明确允许，不进行平台写入与执行出清。

后续要做：网络/机组约束、LMP 归属、结果回测、预测情景与多轮策略优化。不得将这版局部搜索标注为 PMSS 已验证的全局最优方案。
