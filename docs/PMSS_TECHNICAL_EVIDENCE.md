# PMSS 原始机组参数证据审计

## 事实（2025-09-01 单日网架）

在可信服务器上，对 PMSS `powerModel` 的 `units.datas` 读取、与已脱敏的机组报价快照精确按ID核对（10/10一致），发现如下字段：

| 原始字段 | 10台机组的原始取值现象 | 是否直接接入24小时 MILP |
|---|---|---|
| `minCapacity` | 全为0 | 否：仅与报价模型下限一致 |
| `pdAdjustMax` | 与原报价可调最大 MW 均一致 | 否：不等同核实物理Pmax |
| `minOnTime` / `minOffTime` | 全为0 | 否：零的含义与时间单位不明 |
| `incRate` / `decRate` | 全为20 | 否：MW/h或其他单位尚不明 |
| `launchCost` | 全为0 | 否：启动成本项目与计价口径尚不明 |

此外仍没有可信的 `initial_on`、`initial_mw`、`initial_state_hours`、启停过渡爬坡和停机成本。已有 `ThermalConstraints` 最短开停机小时必须大于0，因此不得简单把原始0当作兼容的真实时长。

即使证据完整，单纯看到数值也不能证明 PMSS 使用相同 SCUC/SCED 市场约束。

## 进一步调查老师平台前端代码

当前本地授权读取的课程前端 JS 含以下**代码证据**，但没有验证它们对应历史案例的有效配置：

- 发电机编辑视图内有示例默认值 `minOnTime=7200`、`minOffTime=7200`、`incRate=6`、`decRate=6`。这些是 UI 默认参数，**不是当前10台机组的真实数值**。
- 另一个运行场景视图包含 `ifConMinOnOffTm`（最短开停机约束开关）及 `ifConStartCost`（启机成本约束开关）等字段。
- 应首先核验约束开关是否启用，再确定时间单位（例如是否按秒）及各机组实际初始运行状态，不能直接将7200转换成2小时，也不能把0解释成不限时。

## 改动

- `pmss_technical_evidence.py` 在可信环境读取原始发电机表，严格核对机组ID与容量，只输出**7个白名单数值字段的分布统计**，不复制原始课程对象/项目ID/认证信息。
- `merge_pmss_grid.py` 新增可选 `--include-technical-evidence`，把脱敏来源证据（非真实技术参数）附加到新快照的 `technicalEvidence`。原有快照保持不变。
- `/api/pmss/inspect` 校验来源证据并返回统计及状态：`source_claim_only=true`、`technical_inputs_verified=false`、`joint_milp_ready=false`。上传人可以修改文件，**网页不能证明数据独立真实**。
- React 的联合模型面板展示原始字段覆盖、零值计数、最小最大值及各字段待确认含义。原有严格联合求解门槛不变、仍需10台机组完整参数。
- 无法调用老师 PMSS 写入、保存报价或真实出清。

## 可信服务器离线合并示例

```sh
python scripts/merge_pmss_grid.py \
  --snapshot /private/sanitized-market.json \
  --grid /private/authorized-grid-model.json \
  --include-technical-evidence \
  --output /private/verified-grid-with-evidence.json
```

生成文件为0600权限，拒绝覆盖已有文件。不要把原始网架、Cookie或认证记录上传到GitHub或公开下载页。

## 下一步

对照老师的课程技术说明核实 `incRate` 单位、`minOnTime=0` 和 `launchCost=0` 的语义；在全部初始状态、启停过渡和成本口径核实前，不解除联合MILP真实运行限制。获取多个独立日期历史后另行验证中标预测精度。


## 场景约束查询（只读补充）

原课程前端显示两个查询：`scene/unitParam/list` 与 `project/getUnitInitialStateInput`。前者返回计算约束选项，后者返回初始状态相关字段。另有不同的保存接口，研究流程绝不调用。

新增 `scripts/summarize_pmss_scene_constraints.py` 用于离线读取经过授权获得的完整响应文件：

```sh
python scripts/summarize_pmss_scene_constraints.py --calculation-json /private/calc.json --initial-json /private/initial.json --expected-units 10 --output /private/summary.json
```

该摘要只保留开关原始编码的0/1计数、缺失数量，以及初始字段的覆盖与数值范围；不会输出原始机组行。由于开关编码和时间单位尚未独立验证，0/1 **不能直接解释为启用/关闭**，所有真实联合优化准入仍保持关闭。若返回不完整分页，程序拒绝出具摘要。
