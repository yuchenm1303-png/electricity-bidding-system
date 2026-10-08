# PMSS 只读分析与五段报价（开发中）

本迭代遵循“PMSS = 实际教学市场出清环境；PowerBid = 报价决策层”。保留原有 TeacherPlatformAdapter、Streamlit 和统一价引擎。默认不向 PMSS 保存报价，不执行平台出清。

## 已核验的三个结果 Tab（2026-10-08）

- 机组中标：GET marketResult/unitBid/getSelectTree 返回 T200，两套市场树；POST marketResult/unitBid/listForGd 返回 T200，data.periodNum=24，data.datas 包含 elementId、elementName、marketTypeAtom，以及 power、price、income 的逐时段数据。
- 节点电价：GET marketResult/nodalLmp/getSelectTree 返回 T200，树含39个节点；POST marketResult/nodalLmp/list 使用了错误的机组筛选 ID，因此虽返回 T200 但为空，**不能确认真正筛选参数**。
- 支路潮流：GET marketResult/branchFlow/getSelectTree 返回 T200，树含46条支路；POST marketResult/branchFlow/list 使用机组 ID 返回 T100，**不能视为接口完成对接**。

下一步是按照每个 Tab 自己的树提取 DA、RT 实际元素 ID，查明 POST 请求体并用脱敏真实响应 fixture 锁定字段解析。绝不能将空结果解释为“市场没有节点电价”。

## 数据转换

powerbid.pmss_integration 读取真实机组字段 key、title、mvarate、pdAdjustMax、pdAdjustMin、runningCost、unitType；保留各机组1~24时段及最多五段的分段报价；解析 DA/RT 规则和机组24小时出清结果。

负荷预测必须独立提供24个值和 forecastSource 来源标注，绝不能把事后出清电量悄悄当成未来负荷预测。

已经保存的报价可能超过市场规则接口上限：保留历史读数，不擅自覆盖或改写；正式提交仍需先核验网页校验与课程要求。

## Streamlit 独立入口

新增“PMSS · 24 小时五段报价”页面，接受脱敏 JSON 快照：

- unitTree：真实机组树；
- unitBids：以机组 ID 为键、每个机组的 getUnitBid 响应为值；
- marketSystem：市场规则 getMarketSystem 响应；
- demandForecastMw：长度24的负荷预测数组；
- forecastSource：负荷输入来源。

快照不应含登录凭证、Cookies 或 Tokens。上传前请检查脱敏。

## 策略边界

powerbid.pmss_strategy 使用现有单区域统一价引擎，把各机组的每个报价段拆成供给分段，逐个时段重算，并用坐标搜索优化目标机组每段价格及相邻电量边界。useSameBiddingCurve=1 时，输出统一的24小时五段供给曲线。

这属于**本地代理市场模型**，不是 PMSS 的真实出清，更不是全局最优。尚未纳入机组开停机、最小出力、爬坡、线路拥塞、节点 LMP 和备用约束。runningCost 的真实口径仍需课程核验。

对原有 PMSS bid 生成完整审核报文时必须保留原始的四项成本字段，不可隐式置零。当前 UI 只输出人工审核 JSON，**不存在提交报价和执行出清功能**。

## 未完成的验收项目

1. 节点结果与支路结果通过正确选中 ID 返回真实数据。
2. 用脱敏真实响应补齐单元测试和字段解析。
3. 服务器只读数据安全导出为完整快照，并验证前端全链路。
4. 纳入 LMP、线路和机组运行约束。
5. 只有另行明确授权才可测试真实写入或执行 PMSS 出清。

## 安全只读快照导出命令

在已授权且能够访问 PMSS 的可信服务器上安装项目的 platform 依赖，
通过环境变量 PMSS_BASE_URL、PMSS_PROXY_URL、PMSS_COOKIE_FILE 指向运行环境配置。
PMSS_COOKIE_FILE 必须在 Git 仓库外部，由运维人员单独维护，不得提交或上传到前端。

在服务器上运行 scripts/export_pmss_snapshot.py，并提供 --forecast-json（24元素数组）、
--forecast-source、--case-date 和 --output（仓库外的私有路径）。
脚本只会调用 get_context / get_unit_bid 只读 API，并输出经白名单过滤的
unitTree / unitBids / marketSystem / demandForecastMw / forecastSource。
输出文件权限0600；随后可以上传到新增 Streamlit PMSS 页面做本地计算。

当前服务器缺少该 CLI 所需的认证配置文件验证，尚未声明已完成真实导出。
