# 第十四阶段：老师 PMSS 联合优化参数的13字段证据缺口矩阵

## 目的

前面已经分别接入老师PMSS的发电机参数表**匿名统计**（minCapacity、pdAdjustMax、incRate、decRate、minOnTime、minOffTime、launchCost）和场景约束、初始状态的**匿名统计**（initialState、power、keepTime，以及ifConRamp等原始0/1编码）。

真正要运行24小时机组启停、爬坡、成本联合优化，还需要逐台机组一一对应的完整热机参数、明确物理单位、当前案例状态、约束开关语义、机器身份与课程出处。只有匿名统计**不够**。

本阶段新增一份**不会虚构任何数值**的13字段证据缺口报告，它负责告诉我们“哪些源字段存在、覆盖了多少源记录，还必须核实什么”，不返回真实源机组逐行参数、不替代前一阶段的逐值引用审查。

## 13项研究模型字段对应的当前只读来源线索

以下名称联系只作为**待验证假设**，不表示老师PMSS已证实与我们模型一一对应。

| 联合物理模型字段 | PMSS字段线索 | 尚需要证实 |
|---|---|---|
| min_mw | minCapacity | 是否真实物理稳定出力下限、适用运行模式 |
| max_mw | pdAdjustMax | 申报可调上限是否等于物理运行上限 |
| ramp_up_mw | incRate | MW/h时间基准和 ifConRamp 编码 |
| ramp_down_mw | decRate | MW/h时间基准和 ifConRamp 编码 |
| startup_ramp_mw | 无直接白名单字段 | 启动转换期间最大MW和时长 |
| shutdown_ramp_mw | 无直接白名单字段 | 停机转换期间最大MW和时长 |
| min_up_hours | minOnTime | 单位、0值含义和 ifConMinOnOffTm 编码 |
| min_down_hours | minOffTime | 单位、0值含义和 ifConMinOnOffTm 编码 |
| startup_cost | launchCost | 计价口径和 ifConStartCost 编码 |
| shutdown_cost | 无直接白名单字段 | 停机成本及其单位，不能猜测为0 |
| initial_on | initialState | 初始状态枚举的实际含义、对应机组ID及当前案例 |
| initial_mw | power | 前一时段实际出力MW与启用状态 |
| initial_state_hours | keepTime | 初始状态持续时长的原单位及小时换算 |

**注意：** minOnTime=0可能代表禁用、缺省、或不同运行参数定义；incRate=20可能是不同时间基准下的数值；场景ifConRamp=0/1不意味着已核实启用状态。由代码上的字面字段名无法推断老师引擎内部的实际规则。

## 新增接口和页面

- `src/powerbid/pmss_uc_evidence_gaps.py`：纯只读、严格验证来源摘要。对于每项字段，报告源字段线索、匿名源记录覆盖数、相关未解释开关的原始0/1数量、下一步所需的具体证据。
- `POST /api/pmss/inspect`：在既有快照检查结果增加 `physical_evidence_gaps`；未上传两份摘要时所有13项继续显示“无源观察”，而不会因为源码存在技术字段定义就增加虚假可信度。
- `frontend/src/PMSSJointMwhPanel.tsx`：完整24小时联合研究区域新增可折叠13字段审核表，可以直接查看每项尚需核实的内容。
- `tests/test_pmss_uc_evidence_gaps.py`与`tests/test_pmss_uc_evidence_api.py`：验证匿名字段覆盖不变成已验证参数、部分字段缺失的正确标记、场景开关0/1未误解释、敏感源原始字段不会进入输出、伪造jointMilpReady被拒绝。
- 最终结果始终 `individually_verified_fields=0`、`independent_technical_parameters_ready=false`、`scenario_switch_codes_interpreted=false`。这是当前已收集的匿名来源**证据能力上限**，不是对未来人工认证的否定。

## 研究实践

若已有合法脱敏的老师PMSS原始历史案例，运行现有 `scripts/merge_pmss_grid.py --include-technical-evidence` 可增加原始机组字段的匿名摘要；若经授权有同案例的场景与初始状态响应，运行 `scripts/summarize_pmss_scene_constraints.py` 生成只含计数与数值范围的匿名摘要，再按既有脱敏数据流程保存在私有可信环境。不要将原始平台对象、实际机组秘密信息、Cookie或原始历史快照上传公共仓库。

这些摘要只改善“问题定位”，不会自动解锁真实联合 MILP。真实机组模拟仍需要当前案例、完整逐机组、字段值与单位全部得到独立可信核验。课程参数用户引用一致性属于另一个阶段的审计要求，不能当作平台已验证真实性的证据。

本阶段不访问老师平台、不提交报价、不保存竞价、不运行真实PMSS出清，也不修改节点电价1001这一单日历史假设。
