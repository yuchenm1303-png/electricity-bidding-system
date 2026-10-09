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
