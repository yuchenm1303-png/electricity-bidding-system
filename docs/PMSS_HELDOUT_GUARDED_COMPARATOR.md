# 第二十阶段：把“训练集最优”与“训练阶段保守筛选的规则”分开留出评估

## 已确认的真实三日结论

最新主分支的三日历史数值容差核验，已基于授权环境里的2025-09-01/02/03原始报价和实际中标结果公开以下**聚合MAE**：

| 预先定义的DC同成本分配约定 | 9月1、2日训练 MAE(MW) | 9月3日留出 MAE(MW) |
|---|---:|---:|
| 规范化普通 LP | 26.7264 | **21.5158** |
| 机组ID正序 | **18.4165** | 22.8039 |
| 机组ID倒序 | 39.7800 | 22.4677 |

训练集最优的“正序”在第三日反而比普通LP**恶化约1.2881 MW**。因此绝不应该将单日/训练日的好成绩当成老师真实同价出清规则，或直接将它写入正式报价/利润模型。这也是本阶段代码设计需要避免的问题。

注意：以上数字描述的是历史**原始报价**重放。9月2日和3日原始报价相同，经济报价多样性仍不足。第三日虽在原训练选择之外，仍只有1个留出日期；这些结果没有统计显著性认证，不说明新报价下的老师出清结果。

## 本阶段新解决的问题

第十九阶段已有`predeclaredTrainingGuardrail.trainingOnlyConservativeComparator`字段：训练集样本重复、总体或逐日改善不足时，选择`canonical_lp`作为更保守的参照。然而第十九阶段正式输出中仍然只有`policyLockedUsingTrainingOnly`这个**最低训练MAE赢家**的留出误差。两套规则往往不同，容易让人误以为“保守参照”也已被真正评价，甚至无意将训练赢家代替保守参照投入后续研究。

本阶段使两条路径在结果中清晰分离：

- 训练期只比较预先指定的三条本地DC分配约定，固定选择`policyLockedUsingTrainingOnly`；
- 在**任何留出日期的真实机组出力被读取、误差被计算前**，先只利用训练数据生成`predeclaredTrainingGuardrail`，锁定`trainingOnlyConservativeComparator`；
- 接着在相同的后续留出日期分别评价训练赢家和训练锁定的保守参照。保守参照如果为`canonical_lp`，相对普通LP的变化必然是0，这是数学上同一参照的性质，**不是模型预测能力的外部提升或“无风险保证”**；
- 如果训练门槛确实通过，保守参照就是事先锁定的训练赢家，报告会忠实记录其在第三日可能变差的结果，**不会因留出日失败再偷偷更换为普通LP**。

## 新增报告字段

- `trainingConservativeComparatorMaeMw`：训练数据上锁定保守参照的聚合MAE；
- `holdoutConservativeComparatorMaeMw`：留出日期上该规则的实际聚合历史重放MAE；
- `trainingConservativeVsCanonicalDeltaMaeMw` / `holdoutConservativeVsCanonicalDeltaMaeMw`：相对规范化普通LP的同口径差异（负改善、正恶化）；
- `holdoutConservativeDaysBetterThanCanonical`：保守参照在多少个留出日期中优于规范化普通LP；
- `largestHoldoutConservativeDeteriorationMaeMw`：所选保守参照在留出日期的最大恶化幅度；
- 逐日`holdoutDailyDiagnostics.guardedVsCanonicalDeltaMaeMw`与`guardedBetterThanCanonical`；
- `conservativeComparatorLockedBeforeHoldout=true`：明确执行顺序；
- `conservativeComparatorEligibleForLivePMSS=false`：即便某种本地约定的历史回放误差低，也**不能**据此宣称允许新报价申报或真实PMSS利润预测。

上阶段字段全部保留，报告原有结构未删除。新字段仍只包含日期、已预声明的规则名和聚合误差，不输出原始机组ID、报价、各小时出力、Cookie或项目ID。

## 验收

`tests/test_pmss_tiebreak_holdout.py`新增或强化了以下边界：

1. 训练数据报价曲线完全相同，即使正序MAE显著优于普通LP，**也必须**在训练阶段锁定保守`canonical_lp`；其第三日保守参照误差必须等于普通LP，但训练赢家的第三日恶化仍完整保留。
2. 训练两天报价曲线不同且逐日满足门槛时，锁定正序；第三日可以出现20MW恶化，并如实计入保守参照的留出误差。
3. 对第三日已记录机组中标结果任意修改，允许留出误差随之变化，**不允许**训练锁定的规则或准入理由改变。
4. 没有足够独立日期、仅1日留出、真实原始报价重复等既有风险继续被明确标记。

运行：
```bash
pytest tests/test_pmss_tiebreak_holdout.py -q
pytest -q
ruff check .
python -m compileall -q src app scripts tests
```

本阶段不需要也不会替换老师PMSS的实际出清算法；仍不涉及单日1001节点价格事后拟合或真实收益预测。

**重要限制：** 本次源码测试使用合成数据；9月1日至3日的真实逐日训练门槛究竟能否通过，不能仅凭上表聚合MAE得知，需由具备合法访问权限的可信环境运行更新后的私有离线报告工具。不能把未见过的逐日审核状态硬编码成通过。
