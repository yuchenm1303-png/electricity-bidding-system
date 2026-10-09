# PowerBid Studio — 前后端协作与接口契约

> UI owner: React Studio. Strategy / API owner: 报价策略开发窗口。以 `main` 已实现的 HTTP API 为唯一权威源，避免跨窗口重复实现同一功能。
>
> 2026-10-08 状态：当前 React 前端已连接本地模拟、风险分析和 PMSS 脱敏快照历史研究。**它没有连接老师平台的报价提交或实时出清。**

## 已有可用的公共 API（以实际实现为准）

| 端点 | React 使用方式 | 计算源 | 备注 |
| --- | --- | --- | --- |
| `GET /api/scenario` | 初始机组与市场数据 | `sample_market.json` | 教学样例 |
| `POST /api/optimize` | 单场景和风险分析 | `GridSearchBidOptimizer` / `RiskAwareBidOptimizer` | 同步计算；非 PMSS |
| `POST /api/pmss/inspect` | 读取脱敏 JSON 后展示 24 时段负荷、机组、历史网络诊断 | `snapshot_from_pmss`, `analyze_historical_network` | 仅只读，限约 900 KB；不得上传认证字段 |
| `POST /api/pmss/network-evaluate` | 真实拓扑的本地 DC-OPF 约束对照 | `pmss_grid_bridge` / 网络出清引擎 | 仍非老师平台重出清；需要快照内经核验的网络数据 |
| `POST /api/pmss/optimize` | 24 时段同一条五段价格—电量曲线的本地报价搜索 | `optimize_segmented_bid` | 本地统一价代理模型；不会提交老师平台 |

PMSS 前端使用 `PMSSInspection` / `PMSSOptimization` TypeScript 类型，定义在 `frontend/src/types.ts`，接口调用在 `frontend/src/api.ts`。修改 API 响应结构时，请同时更新这些类型与 `tests/test_pmss_web_api.py`，并提供成功与失败响应示例。

### PMSS 页面含义划分（不可混淆）

- **历史市场数据**：来自用户导入的脱敏 PMSS 快照，其中节点电价、影子价格、线路潮流等是已经发生的出清结果。
- **本地模拟输出**：五段报价推荐、模拟利润和新报价的时段收益均由本地模型计算，并非 PMSS 新报价重出清。
- **历史拟合误差**：只能评价原报价模型与已观察到的结果之间的差距，不能当成新报价收益的可信区间。
- **策略比较**：`strategy_lab.py` 中已有后端 Python 函数，但**尚未有相应的稳定 HTTP API 公开给 React**。React 不自行复制或猜测这些计算。

## 报价窗口后续需要提供的 API（提案，不是现有实现）

为避免另一个窗口接口完成后 UI 再返工，请共同约定新增能力：

1. `GET /api/capabilities`：返回各能力状态，例如 `single_hour`、`risk`、`pmss_snapshot`、`policy_24h`、`pmss_read_only`，每个条目标注 `available`、`source_kind`、`write_enabled`。前端按照状态显示入口，不盲目显示可运行按钮。
2. `POST /api/strategy/policies/compare`：接受经过服务端验证的脱敏场景引用或显式快照，以及风险参数；返回各策略的期望利润、下行利润、可行率、逐时段推荐报价和模型警告。建议响应含 `scenario_source`、`model_kind`、`historical_validation`、`warnings`，避免前端推断。
3. 若计划提供老师 PMSS 直接查询，后端必须先确定身份验证、访问审计、授权范围与访问限制；**不得将 VPN、Cookie、Token 或服务端代理地址暴露给浏览器**。在完成安全设计前继续使用脱敏快照上传。

以上只是协作提案，前端在 API 实际进入 `main` 并通过测试后接入，不提前伪造数据或定义未实现的用户能力。

## UI 集成规则

- 报价窗口拥有 `src/powerbid/**`、平台适配器和新增 HTTP 计算接口；UI 窗口拥有 `frontend/src/**`、组件、图表和响应式样式。
- 两边尽可能各用独立分支，功能提交前对照最新 `main`，避免覆盖他人的更改。
- 同一合并请求必须包含契约说明和测试；未经完整验证不替换生产站。
- 原生浏览器支持减少动态效果，图表初帧必须可见；敏感内容不持久化到 `localStorage`。
- 任何候选报价推荐都不应该提供一个误导性的“已提交 PMSS”成功状态。

## 前端当前仍需后端窗口协作的事项

- 逐小时变曲线策略、动态加价策略、风险参数搜索的 HTTP 契约；
- 老师 PMSS 真实出清结果的合法可读范围与访问控制；
- 复杂约束与代理模型拟合质量的准确返回字段；
- 版本化的数据来源标识，区分课程样例、真实历史快照和当前实时数据。
