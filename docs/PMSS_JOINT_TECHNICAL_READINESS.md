# PMSS 24小时联合机组约束——技术数据准入

本阶段连接现有 joint_market.py 与 joint_strategy.py，没有另写一套联合出清求解器。

## 真实资料现状

真实 PMSS 2025-09-01 快照含机组ID、容量、最小功率、运行成本和申报曲线，但没有可靠的初始运行状态、初始持续时间、爬坡、启停过渡、最短开停机时间及启停成本。不得根据容量或观察到的历史出力推算这些缺失信息。

## 新增能力

- assess_joint_readiness 严格核对10台机组所需全部技术参数；缺失则阻止联合求解。
- compare_joint_legal_candidates 复用已有24h DC+UC MILP，仅比较符合当前市场价格规则的新报价方案，并返回实际本地模拟的24小时出力、启停次数、利润代理。
- 所有输出均为研究模拟，不是PMSS实际出清或结算，且独立验证状态为 false。
- 网页 PMSS分析页显示缺失机组数量，可导出全部技术字段为空值的 JSON 模板；未知数据不会设定虚构默认值。
- 计算量可能很大的联合MILP仅在离线CLI运行，不在无认证公开API暴露求解请求。

## 运行

先检查快照缺失参数：

```sh
python scripts/study_pmss_joint.py --snapshot my_snapshot.json --inspect
```

完整合成教学案例：

```sh
python scripts/study_pmss_joint.py --snapshot data/examples/synthetic_dc_pmss.json --network data/examples/synthetic_dc_network.json --technical data/examples/synthetic_joint_technical.json --technical-source synthetic --technical-description 'synthetic 2-unit example' --target-unit G1
```

技术参数来源可声明 synthetic、user_supplied_unverified 或 course_verified_by_user。声明不等于独立核验；所有联合模型输出均不得用于自动提交真实报价。

下一步需要核实真实课程技术参数和多个独立日期的历史出清数据，才能研究真实机组中标预测是否有所提升。