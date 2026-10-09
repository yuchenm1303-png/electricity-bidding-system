# 第二十三阶段：PMSS 历史节点电价的“共同偏移 vs 节点价差”诊断

## 为什么做这一项

先前获得的 2025-09-01/02/03 真实历史原始报价的 DC 只读回放：
- 9月1日节点电价 MAE 约397.37，显著大于9月2日13.73、9月3日9.78；
- 9月1日少数时段的本地模拟电价出现明显高值，已有“老师历史节点电价约1001、模拟约7000”的例子。但 PMSS 是否限价、如何结算、对偶价格是否唯一以及电价物理单位**尚未独立认证**；
- 不能因为给模拟电价硬截断1001时恰好拟合得更好，就声称老师真实出清或结算确实使用该规则。代码中已有`historical_price_hypotheses.py`专门测试不同**事后限价假设**，但它没有回答“错误是全网同向偏移还是节点之间的相对价差错误”这个不同的研究问题。

本阶段引入与价格截断假说**正交**的诊断维度：只考察模拟 DC 双对偶电价与对应历史 PMSS 节点电价之间的**空间残差形状**，绝不修改求解器、报价曲线、报价策略或 PMSS 原始历史。

## 算法

每小时每个实际观测节点，定义残差 (e_i = p^{DC}_i-p^{PMSS}_i)。只用当天原始报价重放出的**未改动**DC结果。

- `raw_mae = mean(|e_i|)`：真实原报价重放误差，始终保留；
- `signed_median_shift = median(e_i)`：使用老师**已观测**的历史节点电价拟合一个小时内的自由常数。这是明确标注的**EX-POST 事后诊断**，不是可预测的偏移；
- `median_centered_mae = mean(|e_i-median(e)|)`：假设允许事后选一个全网共同偏移，节点间**仍不能消除**的平均绝对残差。这是对“纯空间价格形状偏差”的描述，不是真实出清精度；
- `residual_range = max(e_i)-min(e_i)`：各节点残差的空间极差；
- `uniform_shift_within_tolerance`：只有当至少2个节点有真实观测，且残差极差 `<=1e-5`（**数学比较容差**、非PMSS规则）时才为真。

**只有一个可用节点时不得声称全网共同偏移。** 此时只保留原始MAE，median、centered MAE、残差极差、uniform判定全部输出`null`，不让单点样本凭空获得0均值误差。

## 与现有历史报告的衔接

- `src/powerbid/price_residual_shape.py`：新增只负责数学残差几何的纯函数；
- `src/powerbid/historical_validation.py`：在原始报价24小时DC回放同一循环里，直接用已经计算好的**原始有符号节点误差**附上五类不含机组/节点身份的小时指标，不额外重新运行模型；
- `src/powerbid/historical_error_profile.py`：每个历史日期增加 `priceResidualStructure`。只对每小时至少有2个观测节点的时段聚合，并保证`rawMaeOnSameEligibleNodes`和`bestExPostHourlyUniformShiftMae`**使用完全相同的节点小时样本**，避免缺测数值假改善。
- 原有`mae.nodalPrice`、`coverage.nodalPrice`、`worstHourlyMae`与`holdoutNodalPriceMae`**完全不变**，仍按未经校正的DC输出计算。全部新增值仅出现在私有匿名报告中。

`bestExPostUniformShiftReduction`表示如果**事后已经看见**该小时的真实全部节点价格，最多可以消去的MAE份额；`bestExPostUniformShiftFraction`只是这个比率而不是预测能力。若没有观测或原始MAE为0，比例为`null`。常数偏移量越大、中心化剩余误差越小，可能提示需重点研究**价格口径、单位、价格水平、对偶变量退化或结算变换**；但哪一条成立仍需独立核实老师平台说明文档。中心化后仍显著有误差时，应重点研究**网络拥塞、边际机组/出清与实际节点价差**，也不能由此直接证明原因。

## 安全与验证

新增`tests/test_price_residual_shape.py`覆盖：共同偏移、部分节点偏移、奇数节点中位数、缺测单节点不制造虚假的0空间误差、非法NaN/inf/容差、原始MAE不被校正覆盖、完整24小时的三天报告、严格匿名化以及旧`HourlyError`构造兼容。

真实三天原始快照受可信服务器root权限保护，当前开发账号**不绕过权限读取**，因此本阶段没有宣称计算出真实9月1日空间残差分解的最终数值，也没有在现有三天小样本上宣称“发现了价格限价规则”。

在有权访问真实三份历史文件的可信私有环境下，可直接运行既有命令（无需任何新的PMSS登录）：

```bash
python scripts/report_pmss_hourly_errors.py \
  --max-unit-mae-mw 20 --max-nodal-price-mae 50 --holdout-days 1 \
  --output /private/pmss-hourly-price-shape.json \
  /private/day-2025-09-01.json \
  /private/day-2025-09-02.json \
  /private/day-2025-09-03.json
```

此导出只创建新的0600文件，原历史数据不写入GitHub、不上传网站。不参与真实报价校正、新报价反事实出清或收益预测；保留`priceRuleVerified=false`和`exPostCommonShiftIsNotProspectivePriceCorrection=true`。
