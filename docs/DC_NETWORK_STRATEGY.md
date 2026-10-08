# PowerBid Lab：网络约束报价与 PMSS 历史反馈（DC V1）

## 研究定位

这是**独立的电网约束报价研究引擎**，不会连接、保存、触发或修改老师 PMSS 的任何市场出清。它用于回答：在一个已核实的网络拓扑上，不同报价曲线如何改变**本地 DC 模型**的机组中标、线路潮流和节点边际电价（LMP）。

与旧的单区域 uniform-price 模型不同，DC V1 可显式识别因线路容量受限而产生的节点价格差和机组出清差异。它不是老师 PMSS 的完整网络市场模型，也没有能力根据历史 LMP 推断“新报价的真实 PMSS LMP”。

## 模型

使用 \`scipy.optimize.linprog(method="highs")\` 求解每小时最小化总申报报价成本的线性规划（非福利-最大化的完整 SCUC）：

\[
\min \sum_{g,k} c^{bid}_{gk}q_{gk}
\]

每个节点满足：

\[
\sum_{g\in n,k} q_{gk} - \sum_{\ell\text{ from }n} f_\ell
+ \sum_{\ell\text{ to }n} f_\ell = D_n.
\]

每条线路（电抗 \`reactancePu\` 为标幺，\`baseMva\` 为 MVA）：

\[
f_\ell=\frac{S_{base}}{x_\ell}(\theta_{from}-\theta_{to}),\quad
-\bar{F}_\ell \leq f_\ell \leq \bar{F}_\ell.
\]

各报价段限额：

\[
0\leq q_{gk}\leq Q^{bid}_{gk}.
\]

固定一个参考节点的相角，节点功率平衡等式右端项的优化对偶值为 **DC 线性模型的边际节点电价**。这是**无损直流近似**，不是 PMSS 的实测电价；价格在退化 LP 下可能非唯一。

注意本模型不考虑：交流电压、无功、有功损耗、N-1、安全约束、备用、机组启停、最小稳定出力与爬坡的**联合市场出清**、日前/实时联动与真实市场收费。上一个阶段实现的机组物理约束模块可以对本模型中标24小时序列做**事后筛查**，但不等于这些约束已经嵌入 DC 市场 LP 内部。未提供物理限制时明确标记为未筛查。

## 数据输入格式与禁止猜测规则

网页独立页面 \`app/pages/4_DC节点报价研究.py\`，在 Streamlit 页面导航中可见。

必须上传两个文件：

1. **PMSS 脱敏只读快照**，与此前 \`snapshot_from_pmss\` 使用相同格式，必须包括 \`unitTree\`、\`unitBids\`、\`marketSystem\`、\`demandForecastMw\`、\`forecastSource\`。
2. **核验过的 DC 网络输入 JSON**，准确包含以下顶级字段（其他字段被拒绝，防止混入意外数据）：
   - \`buses\`：所有节点 ID 数组，无重复；
   - \`lines\`：\`{lineId,fromBus,toBus,reactancePu,limitMw}\` 数组；
   - \`unitBus\`：每台机组 ID → 已核实节点 ID，覆盖全部机组，不许猜测；
   - \`hourlyDemandMw\`：每个节点 24 个 MW 需求值，求和每小时必须与 PMSS 快照 \`demandForecastMw\` 一致；
   - \`slackBus\`：网络已知参考节点；
   - \`baseMva\`：模型对应基准容量；
   - \`topologySource\` 和 \`demandSource\`：明确来源，且 demandSource 必须与 PMSS forecastSource 完全一致。

连接性、电抗非零、线路限额、总需求、数据来源、机组 ID 均严格校验。没有核实的 PMSS 39 节点、46 线路电抗与有功限额，不允许直接把这份离线 DC 模型叫作“老师真实电网已接通”。

可选第三个**核实物理参数 JSON**，字段必须准确等于 \`ThermalConstraints\`：
\`unit_id,min_mw,max_mw,ramp_up_mw,ramp_down_mw,startup_ramp_mw,shutdown_ramp_mw,min_up_hours,min_down_hours,startup_cost,shutdown_cost,initial_on,initial_mw,initial_state_hours\`。
未提供时页面必须注明“物理约束未筛查”；提供时筛除在任意合成压力情景下存在已知目标机组运行约束违例的报价，若没有候选通过则不输出伪可行推荐。

## 风险与利润

候选来自 PowerBid 原有策略 \`generate_policy_plan\`，每个报价方案在全部 24 小时与多个**合成**负荷/竞争对手报价压力情景中重新进行 DC 网络出清。

\[
\Pi_{t}^{DC}=
(\lambda_{n(g),t}^{DC}-c^{assumed}_g)
Q_{g,t}^{DC}\cdot1\mathrm{h}.
\]

每个候选报告：

- 24h 模拟期望能源毛利（不扣启动成本）、最差情景毛利；
- 概率加权尾部下行情景毛利；
- 综合风险得分与目标机组期望中标量；
- 目标机组所在节点的模拟 LMP、各线路模拟潮流。

这些值来自本地假设，不是 PMSS 回传利润，也不自动计费或执行外部报价。

## 历史回测和严格边界

如果快照包含 \`results\`，则只允许对 **PMSS 原始已申报报价** 的中性情景模型重算与**同一日**已出清结果做对照。要求 \`baseline.periods == snapshot.bids[target_unit_id]\`、原机组 ID/市场类型一致、39/46 等所有节点与线路 ID 严格一致。

误差指标：

- 目标机组中标出力 MAE / RMSE；
- 目标机组价格 MAE（仅诊断，不假设与本地 LMP 同结算口径）；
- 全网节点价格 MAE；
- 线路**绝对值潮流** MAE（避免未经确认的 PMSS 支路流向引入假误差）。

缺失历史时段不以 0 代替，覆盖率独立报告；真实历史数据不能拿来当作新策略的 PMSS 出清反馈。要论证预测精度还需不同日期的留出回测，并核对实际出清算法和成本口径。

## 立即可运行的合成示例

项目附了三份明确标注为 **synthetic** 的教学示例，**不是 PMSS 实测数据**：

- \`data/examples/synthetic_dc_pmss.json\`
- \`data/examples/synthetic_dc_network.json\`
- \`data/examples/synthetic_dc_g1_physical.json\`（可选）

两节点示例：G1 位于 A，出价 60；G2 位于 B，出价 90；负荷 160 MW 位于 B；A→B 线路上限 30 MW。在简化 DC 出清中，G1 只向 B 输送 30 MW，G2 承担 130 MW；A、B 节点电价不同。此结果用于检查“电网阻塞影响中标与节点边际价格”的基础逻辑。

运行：

\`\`\`bash
pip install -e '.[ui,strategy]'
streamlit run app/streamlit_app.py
python -m pytest tests/test_network_strategy.py -q
\`\`\`

## 下一阶段

1. **与另一窗口接口协作**：获得老师 PMSS \`getPowerModel\` 或相关电网接口的已核实节点/机组/线路字段、端点、电抗、标幺基准和线路有功约束，增加白名单解析器，不能猜字段或透传认证信息。
2. **物理联合调度**：将机组 MILP 启停/爬坡限制嵌入节点网络调度（这意味着在混合整数市场模型定价时，需要正确处理固定整数状态后的线性价格计算）。
3. **按日期留出校准**：历史案例按天分训练/验证，评估 LMP、机组中标出力和线路潮流误差，不能只用一个历史案例宣布网络模型可靠。
4. **授权测试 PMSS 闭环**：严格限制提交次数，备份原报价，选择独立教学实验案例，经授权后执行实际出清，读取结果，恢复环境并保存审计记录。当前代码故意**没有**平台保存或执行调用。

