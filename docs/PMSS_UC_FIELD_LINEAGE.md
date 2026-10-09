# 第十三阶段：PMSS 联合机组优化参数的逐字段来源审核

## 为什么需要这个阶段

此前 React 的高级研究面板允许上传完整机组参数 JSON，填写一句“课程参数已核实”并勾选确认，就启动24小时联合DC+UC模型。这在研究演示中可以运行，但**没有把实际参与计算的每个数值与核实依据绑定**。文件之后发生修改、案例日期或单位不一致，也没有独立来源清单进行核对。

本阶段解决数据审核的可追溯性，而**不是宣称我们已经拿到老师PMSS真实SCUC/SCED完整参数**。

## 当前老师平台真实只读字段的证据状态

已有证据模块能够读取教师平台机组参数表的minCapacity、pdAdjustMax、minOnTime、minOffTime、incRate、decRate、launchCost字段的统计，以及场景计算开关和初始状态输入的**匿名只读统计**。目前已观察的历史案例中，部分时长/成本字段为0，部分速率字段相同；但字段的物理单位、零值语义、开关编码、场景到机组的精确对应关系与课程结算规则仍需进一步核实。

因此这些匿名统计**绝不会自动转换成完整ThermalConstraints记录**，不会自动填写零初始状态、最短开停机、启动费用、停机费用或过渡爬坡。实际PMSS物理预测仍锁定。

## 逐台机组的可审阅来源清单

在已有的技术参数JSON之外，现在要求课程来源用户额外提供一份独立JSON：

- schema_version固定为1；
- case_date必须与当前脱敏PMSS历史研究快照完全一致；
- source_kind固定为course_manual_user_attestation；
- units必须与该研究日机组ID完全一致，不能少机组也不能多机组；
- 每台机组有13个技术输入字段的独立条目，字段包含value、unit、reference；
- value须与上传并最终用于MILP计算的数值完全一致，布尔值和整数严格区分；
- unit须显式填写，普通/初始功率为MW、连续爬坡为MW/h、启停过渡功率为MW/transition、最短状态时间为h、开停机费用按申报成本口径bid-cost/start或bid-cost/stop；
- reference须注明具体手册、页码或资料版本。空引用、URL查询参数、密码/Token/Cookie等隐私信息不作为引用；
- 被修改的技术输入不会自动沿用原本的来源清单，必须重新核对对应value。

React高级研究面板可以直接根据已经上传的完整技术参数生成**带value和unit、reference保持空白**的审核模板。只有人工从真实课程资料逐项补全后，才可以再次导入并开始计算。API上不提供回退路径，不能凭一段普通说明绕过来源清单。

### 示例，仅说明数据结构，不代表真实技术参数

    {
      "schema_version": 1,
      "case_date": "2025-09-01",
      "source_kind": "course_manual_user_attestation",
      "units": {
        "SYNTHETIC_G1": {
          "min_mw": {"value": 15, "unit": "MW", "reference": "课程实验手册v1第12页，机组G1参数"}
        }
      }
    }

注意，上面只展示一个字段以说明形式，**不是完整或可通过审核的清单**；必须给每台机组全部13项字段填写证据。

## 严格区分“引用齐全”和“来源可信”

合法清单仅证明**用户提供的文献引用与计算参数具有一致性**，不代表平台独立检查过手册、论文或老师后端算法。接口返回technical_lineage_audit，显示机组/字段覆盖、逐值匹配情况，同时保持：

- user_source_attested=true
- independent_pmss_semantics_verified=false
- safe_for_live_submission=false
- counterfactual_pmss_verified=false
- pmss_write_performed=false

synthetic来源继续允许显式教学合成测试，但不得附带课程真实性声明。课程来源没有清单则拒绝，来源未知或仅由旧PMSS只读匿名汇总“补齐”的字段同样拒绝。

## 改动位置

- src/powerbid/pmss_physical_lineage.py：新增完整逐字段审阅模板生成、严格单位/数值/引用/身份/日期校验与审计统计。
- app/pmss_api.py：强化POST /api/pmss/network-joint-mwh-range课程来源准入，缺technical_lineage则422，不更改原24小时联合MILP计算和模拟结果。
- frontend/src/PMSSJointMwhPanel.tsx：支持下载空引用模板、上传来源清单；技术参数文件、来源说明一经变更即清除旧确认及结果。
- frontend/src/api.ts、frontend/src/types.ts：传输清单并显示已核对字段数，明确没有独立认证。
- tests/test_pmss_physical_lineage.py与原API合同测试：拒绝错误单位、数值过期、缺字段、错误案例日期、敏感链接和不可信源。

## 下一步的数据验证

真正解锁老师 PMSS 真实机组联合优化，仍需要逐台核实初始状态编码、持续时间单位、连续/启停爬坡以及启停成本单位和市场费用口径。课程文档或老师平台实际源代码有了可靠材料后，再将每条数值与具体证据对应，并使用不同日期、不同负荷工况完成独立留出回测。

所有本阶段功能完全本地计算；不登录老师平台、不保存报价、不触发实际出清，不将私有源数据或凭据提交GitHub。
