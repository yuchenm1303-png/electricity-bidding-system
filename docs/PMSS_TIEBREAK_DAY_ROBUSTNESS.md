# 第十九阶段：同成本机组分配规则的逐日期稳定性与报价重复审计

## 改动动机

前阶段已有按时间锁定“训练前两日、检验第三日”的规则比较，但输出主要是各期合并 MAE。合并平均误差可能掩盖**规则只对一天有效，却在另一日明显恶化**；同时2025-09-02和09-03历史原始报价曲线一致，不能仅因它们的日期不同，就假定是两个不同报价策略的外推验证。

本阶段在保留原有模型与训练锁定规则的前提下，增加**每一日独立误差、保守训练门槛、重复报价识别和样本量声明**。

## 新增聚合审核口径

- `trainingDailyDiagnostics` 和 `holdoutDailyDiagnostics`：每一天分别记录三种事先声明的规则的机组中标量 MAE、锁定规则与规范化普通LP之差。差值为负表示误差改善，为正表示变差；原始机组ID、历史报价段与中标明细不输出。
- `trainingSelectedDaysBetterThanCanonical` 与 `holdoutSelectedDaysBetterThanCanonical`：分别统计改善的日期数，而不仅是总体加权改善。
- `largestHoldoutDeteriorationMaeMw`：报告最差日期里锁定规则比规范化普通LP恶化了多少。没有恶化时为0。
- `trainingDistinctOriginalBidCurves` 与 `holdoutDistinctOriginalBidCurves`：按整个24小时全部机组的原始报价曲线指纹统计不同曲线的数量，指纹不输出。**物理上相同的边际价格但不同的原始分段，也属于不同“原始曲线编码”，并不必然等价于独立竞价策略**。
- `holdoutDatesReusingTrainingBidCurves` 和逐日 `identicalOfferCurveSeenInTraining`：指出后续留出日期是否沿用了训练日的**全部机组完整报价曲线**。真实的9月2/3报价重复可能导致这项标记为真；具体结果应由具备权限的私有运行环境验证，不能在代码中硬编码。

### 训练集专用的保守门槛

`predeclaredTrainingGuardrail`：
- `minimumMeaningfulImprovementMw` 默认1MW，可由CLI的 `--min-training-improvement-mw` 在查看留出结果**之前明确决定**，限制在(0,100]MW；
- 只有训练所选规则不是规范化LP，至少有两套不同原始报价曲线，并且**所有训练日和训练期总体** MAE均较规范化LP改善至少该门槛，才返回 `passed=true`；
- 不通过时 `trainingOnlyConservativeComparator=canonical_lp`；同时仍保留原 `policyLockedUsingTrainingOnly`，方便审核研究最小MAE规则与更加谨慎的默认参照之间的区别；
- 这个门槛是人为指定的工程筛选条件，**不是统计显著性检验，也不是老师真实同价规则的认证**。即使通过，也不能自动激活真实报价或收益预测。

### 按天留出样本不足

三天案例只有1天留出，因此明确返回
`holdoutRobustnessAssessment=ONLY_ONE_HOLDOUT_DATE_NO_STATISTICAL_CONFIDENCE`。
如取得更多日期，可设置至少2天留出，但即使有2日留出，这里仍标记
`DESCRIPTIVE_MULTIDAY_HOLDOUT_NO_STATISTICAL_CONFIDENCE`。系统不伪造置信区间或p值。

`statisticalSignificanceEstablished=false`、
`readyForForwardBidOptimization=false`、
`validatedNewBids=false`、
`actualPMSSRankingRuleVerified=false`
始终保持。

## 私有离线操作

```bash
python scripts/report_pmss_tiebreak_holdout.py \
  --holdout-dates 1 \
  --min-training-improvement-mw 1 \
  --output /private/pmss-historical-tiebreak-day-audit.json \
  /private/2025-09-01.json \
  /private/2025-09-02.json \
  /private/2025-09-03.json
```

必须有读取三个原始历史文件的正式权限。程序只读历史原始报价、节点负荷与老师已记录的原出清中标，输出新的0600匿名汇总报告，拒绝覆盖输出和缺失逐时观测。它**不连接 PMSS、不提交报价、不执行出清**。

当前开发会话的真实三日源文件仍由其它账户的root:root 0600权限保护；本阶段不尝试以非授权身份读取，不能把测试用合成机组和数据的优劣冒充真实第三日排名。

## 验收要点

测试使用合成数据专门模拟“前两天规则改善、第三天明显恶化”，并进一步对第三日观测作任意修改，核对**锁定规则和事先声明的训练门槛完全不变**。覆盖逐日期错误统计、重复报价日期、缺失日期、非法门槛、输入顺序与私有报告覆盖保护。

这个扩展是**历史原报价模型的可信度审计**，不是新报价策略的上线条件判定，更不等于已证实老师平台最优出清逻辑。三日数据仍不足以支持稳定外推或未来利润结论。
