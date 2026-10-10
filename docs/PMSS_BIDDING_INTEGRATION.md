# PowerBid Studio · PMSS 七步报价策略集成

## 集成范围

本分支仅将已存在的只读接口、策略引擎和人工交接能力串联，不调用老师平台的写入或出清接口、不存储平台凭据，也不修改液态玻璃鼠标、登录界面和生产部署。

| 阶段 | 复用现有能力 | 数据真实性与限制 |
| --- | --- | --- |
| 1. 选择真实案例 | `POST /api/pmss/inspect`，现有脱敏快照导入入口 | 案例与机组 ID/日期由只读快照标注；服务器只读案例列表由窗口 A 接入后使用，当前不伪造“在线案例选择” |
| 2. 预测/负荷输入 | `demandForecastMw[24]`、`forecastSource`、`loadSourceKind` | 当前**没有独立预测器**；仅复用带来源标注的 24h 序列，历史输入不是未来预测 |
| 3. 策略优化 | `/api/pmss/optimize`、`/api/pmss/network-rank` | 前者是单区统一价近似，后者是核实 DC 网络 + 合成竞争报价扰动的风险排序；均非 PMSS 真实出清 |
| 4. 五段报价 | `pmssBiddingFlow.ts` 提案适配器 | 用户明确选择单区域推荐或网络排序首名，校验机组、容量、市场价格限额和连续段；**24 小时共用一条曲线** |
| 5. 人工提交 | `PMSSManualClearingPanel` CSV/审核 JSON | 只供授权人员在老师页面自行核对/操作；不提供正式报文，`platformSubmitted=false` |
| 6. 导入出清结果 | `POST /api/pmss/manual-clearing-review` | 日期、DA/24h、目标机组、容量、历史原结果重复检测，人工确认；不允许以旧历史结果冒充新的验证 |
| 7. 收益与误差复盘 | `powerbid.pmss_manual_result_review` | 展示逐时段真实观察 MW 与本地代理模型 MW 的 MAE、老师返回 `income` 合计；`income` **不是已核算净收益**；结果关联仅是人工声明 |

## 工作台交互

- 导入案例后顶部出现七步状态看板和负荷来源提示。
- 选择机组后，可执行单区域五段优化；如包含可信 `dcNetwork` 且是历史只读案例，可执行网络风险排序；点击**采用单区域推荐**或**采用网络风险排序第 1 名**明确生成一条待审核的统一提案。
- 下载含日期、机组 ID、策略来源、逐段 MW/价格的 **REVIEW_ONLY JSON**。真实平台提交需人工审查，该 JSON 不是平台原生申报格式。
- 选中的曲线会传给现有独立 24h DC 网络对照（若有电网）和人工结果复盘；原来的五段模型与网络排名仍保留自己的报告，避免相互冒充。
- 更换案例、目标机组、风险参数或优化搜索参数，当前候选和已关联结果即失效。重新选择提案前不能再进行人工交接。
- 导入人工结果会调用后端**重新计算被选定曲线**；只有通过严格校验才显示观察结果与误差。重新勾选确认或重新上传结果会清除先前复盘状态。

## 与 A/B/C 窗口的边界

- **窗口 A（PMSS 数据）**：沿用 `unitTree` / `unitBids` / `marketSystem` / `demandForecastMw` / `dcNetwork` 快照合同及 `/api/pmss/inspect`。未来 A 接入授权只读的服务器案例目录时，工作台可在相同快照结构上复用集成面板，本分支不捏造 API 地址或访问权限。
- **窗口 B（机组网络）**：继续复用 `network-evaluate` / `network-rank`，其输出属于线性 DC 网络独立逐小时出清，**不等于**已用经核验的初始启停/爬坡参数运行 24h 联合 SCUC/SCED。
- **窗口 C（React 工作台）**：新建局部面板，不修改 React 应用路由、页面样式体系、Smirel 资产或鼠标源码，不覆盖并行开发的主工作区。

## 证据标记与安全

- `PMSSBidProposal` 始终为 `shared24hCurve=true`、`platformSubmitted=false`、`pmssCleared=false`；
- 审阅导出强制 `manualReviewOnly=true`、`pmssCandidateResultVerified=false`；
- 人工结果 API 原有 `association=OPERATOR_ASSERTED_ONLY`、`candidate_bid_causality_verified=false`、`teacher_result_authenticated=false` 和零写入标记原封不动；
- 不根据回测历史价差声称新五段曲线的实际收益；仅将老师平台的历史原报价 MAE 用作模型拟合诊断；
- 出清结果缺少老师独立签名/提交 ID 与已核验的新报价映射时，绝不标为因果验证成功。

## 开发测试

```bash
cd frontend
npm ci
npm run test:workflow
npm run build
cd ..
pytest -q
```

PR CI 同时运行 Python pytest/ruff 与 Node 22 的候选合同测试、TypeScript 编译和 Vite 构建。测试均使用合成夹具；**不表示已取得真实 PMSS 新报价授权验证**。

### 已知后续工作

1. 等 A 窗口提供授权只读案例/日期/机组选择接口及实时查询契约后替换手动导入交互；本分支没有提供不存在的在线接口。
2. 如需真正的预测阶段，接入独立预测模型与时间切分/留出样本，并标注训练数据、预测时点及可信度。
3. 获取老师平台可独立验证的出清提交关联 ID/签名，才能将人工关联结果升级为客观的新报价评价。
4. B 窗口取得全部机组的经核验的启停、爬坡和初始状态后，再把真实 24h 联合 MILP 结果纳入策略决策。
