# Architecture

## 1. 设计原则

PowerBid Lab 不尝试从零复制完整 ISO/RTO 电力市场，而是把课程题目拆成两个稳定边界：

```text
报价决策层                          市场环境
┌──────────────────────┐          ┌──────────────────────┐
│ 数据 → 候选报价 → 优化 │ ───────→ │ 出清 / 调度 / 网络约束 │
│          ↑           │ ←─────── │ 价格 / 电量 / 潮流     │
│       收益反馈        │          └──────────────────────┘
└──────────────────────┘
```

报价算法只依赖统一的 `ClearingEngine` 接口，不直接依赖某一个网页、PyPSA 或 ASSUME。

这样做的好处是：老师平台的接口形式尚未明确时，我们仍然可以完成报价算法、实验与 UI；后续只替换 Adapter，不推翻整个项目。

## 2. 当前领域模型

### Offer

单台机组一个市场时段的供给报价：

- `unit_id`
- `quantity_mw`
- `bid_price`
- `marginal_cost`

其中 `bid_price` 是向市场提交的价格，`marginal_cost` 是用于计算真实利润的成本，两者必须分开保存。

### MarketScenario

描述一个试算场景：

- 市场负荷 `demand_mw`
- 时段长度 `interval_hours`
- 目标机组 `target_unit_id`
- 所有机组报价 `offers`

### ClearingEngine

统一接口：

```python
clear(scenario: MarketScenario) -> ClearingResult
```

`ClearingResult` 至少返回：

- 统一出清价；
- 每台机组中标 MW；
- 总供电量；
- 未满足负荷。

## 3. 当前出清引擎

### Built-in uniform-price engine

只用于课程 MVP 与算法单元测试：

1. 按报价从低到高排序；
2. 依次接受供给，直到满足负荷；
3. 边际报价决定统一出清价；
4. 同价边际报价按容量比例分配剩余需求；
5. 所有中标机组按统一出清价结算。

这个引擎故意保持简单，不包含线路、机组组合、爬坡、启停成本等复杂约束。

### PyPSA engine

`PyPSAClearingEngine` 已作为可选 Adapter 加入。第一版按单市场区建模：

- `Generator.p_nom` ← 申报容量；
- `Generator.marginal_cost` ← 报价；
- `Load.p_set` ← 市场负荷；
- `Network.optimize()` ← 市场优化；
- `buses_t.marginal_price` ← 出清价格；
- `generators_t.p` ← 中标电量。

下一阶段把老师截图里的 Bus / Line / reactance / transmission limit 映射成 PyPSA 网络，直接复用成熟的网络优化能力。

## 4. 报价优化

第一版采用网格搜索，而不是直接上机器学习：

```text
180 → 出清 → 利润
190 → 出清 → 利润
200 → 出清 → 利润
...
390 → 出清 → 利润
400 → 出清 → 利润
        ↓
选择利润最大的可行报价
```

统一价市场下目标机组的单时段利润：

```text
利润 = (统一出清价 - 真实边际成本) × 中标MW × 时段小时数
```

后续优化器可以替换为：

- 贝叶斯优化；
- 鲁棒/随机优化；
- 多目标优化（利润 + 风险）；
- ASSUME 风格策略；
- 强化学习。

## 5. 数据来源规则

不允许把“自己编的数”伪装成真实数据。每个场景都应标明来源：

1. `platform`：老师仿真平台/API/导出文件；
2. `course`：课程材料或老师提供数据；
3. `public`：公开电力市场数据集；
4. `synthetic`：人为构造的教学仿真场景。

当前 `data/sample_market.json` 明确标记为 `synthetic`。

## 6. 老师仿真平台 Adapter

在确认平台能力前，不把网页耦合进核心代码。需要先确认平台是否提供：

- REST/WebSocket API；
- CSV/Excel 导入导出；
- 报价提交接口；
- 出清结果下载；
- 登录/鉴权方式；
- 是否允许自动化调用。

理想的数据映射：

```text
老师平台数据
  ↓
TeacherPlatformAdapter
  ↓
MarketScenario
  ↓
报价优化器
  ↓
候选报价
  ↓
TeacherPlatformAdapter.submit(...)
  ↓
ClearingResult
```

如果平台没有 API，第一阶段可采用“导出/导入文件”或人工录入，不使用脆弱的浏览器抓取作为核心依赖。

## 7. 后续阶段

### Phase 2 — 网络约束

加入 Bus、Line、reactance、capacity，并通过 PyPSA 计算：

- DC/线性潮流；
- 线路拥塞；
- 分区/节点价格；
- 机组受网络约束后的实际中标量。

### Phase 3 — 多时段

加入：

- 24h 负荷曲线；
- 风光预测；
- 爬坡约束；
- 最小开停机时间；
- 启停成本；
- 储能。

### Phase 4 — 预测与风险

加入：

- 历史出清价预测；
- 负荷预测；
- 新能源出力预测；
- 竞争对手行为场景；
- 概率利润、CVaR 等风险指标。

### Phase 5 — 智能策略

把状态、动作、奖励定义清楚后，再引入强化学习，避免用 AI 替代尚未验证的市场模型。
