# 第十五阶段：PMSS 同案例只读证据的安全离线绑定

## 本阶段真实排查结果

可信服务器上的2025-09-01 PMSS 10机组基础历史快照没有附带 `technicalEvidence` 和 `sceneConstraintEvidence`。另有一份名字指向“已观察技术参数”的私有文件，但权限为 root:root 0600，普通开发账号无权读取。**本阶段没有使用 sudo 或其他方式绕过原文件权限，也没有读取这份私有文件**。

此前对学校VPN和PMSS的诊断表明，VPN健康并不能表示教学网站的应用登录仍有效；网页后端可能明确返回登录超时。没有可用的已授权业务会话与场景源响应，就无法声称完成了新的真实参数采集。本阶段因此优先完成离线、可审核的数据准备工具，等待管理员按既有权限流程提供合法的只读原始资料。

## 新增：案例绑定匿名证据附加工具

`scripts/attach_pmss_evidence.py` 接收：
- `--snapshot`：已经脱敏、日期明确、具有核验过的 `dcNetwork` 的历史只读报价快照；
- 可选 `--technical-grid`：有权限读取的原始PMSS电网JSON中的机组表，用以先严格按实际机组ID联结，再只输出匿名的7字段统计；原始机组ID表/私密字段不进入新快照；
- 可选 `--scene-summary`：使用现有 `summarize_pmss_scene_constraints.py` 生成的、只包含开关计数和初始字段覆盖/范围的匿名摘要；
- 如果存在场景摘要，还**必须明确提供** `--scene-case-date` 和 `--scene-source-note`，且日期与历史快照 `caseDate` 完全相同；这只是操作人员对同一案例的声明，不是平台认证；
- `--output`：一个尚不存在、位于已建立的可信私有目录中的新文件。

示例（以下均为占位私有路径，不代表可读取真实服务端 root 文件）：

```bash
python scripts/attach_pmss_evidence.py \
  --snapshot /private/pmss-da-case-2025-09-01.json \
  --technical-grid /private/authorized-grid.json \
  --scene-summary /private/scene-summary.json \
  --scene-case-date 2025-09-01 \
  --scene-source-note "课程案例2025-09-01的只读场景响应，已人工核对对应日期" \
  --output /private/pmss-case-2025-09-01-evidence.json
```

可仅附加机组摘要，此时不需要场景日期声明；若已有合规的旧机组技术摘要，工具可以继续保留它，但会将来源关联标为 `legacy_summary_only`，不能假装重新完成了机组 ID 原始表核验。

工具严格验证历史标志、案例日期、源机组与报价身份、DC网架、场景摘要schema/覆盖、禁止认证信息字段与未知JSON键。输出采用O_EXCL独占创建，权限0600，拒绝覆盖旧输出、符号链接/别名。原始文件不会修改，原始机组/场景行不会复制到输出。

## SHA-256 不证明来源真实性

新快照只新增受限的 `evidenceBinding` 元数据：

- `caseDate`与历史快照案例一致；
- `technicalSha256` 和 `sceneSha256` 对附带的**匿名统计内容**作规范化JSON哈希；
- `technicalAssociation` 为严格原始ID联结、旧摘要或缺失的准确类别；
- `sceneAssociation` 只有“操作人员确认与此案例对应”或缺失；
- `independentlyVerified=false` 永久保留；摘要哈希只能发现**之后的修改/错配**，没有任何能力确认老师平台的数据库、初始状态编码及结算规则。

`POST /api/pmss/inspect` 会在存在该元数据时验证摘要内容哈希、日期和保守声明。一旦匿名摘要被修改或案例标签发生错配，直接返回422；合法时只返回 `evidence_binding` 可信范围内的状态，绝不回显原始身份和场景注释。旧快照仍能加载，但 `evidence_binding=null`，页面明确显示其“尚无同案例绑定”。

## 不能把什么冒充真实参数

匿名7个机组字段、场景0/1开关计数、初始值分布及其SHA-256仍然**无法映射成目标机组完整13项热机参数**。本阶段不会推断机组启动/停机转换爬坡、初始功率、初始状态、费用单位，不会取消原本每台每字段的课程来源审计与24小时物理研究准入门槛。

本阶段全部操作均为本地离线分析，不向老师PMSS登录、提交报价、保存数据或触发出清，不修改市场定价（包括未证实的1001节点电价假设）。

## 验收

```bash
pytest tests/test_pmss_evidence_attachment.py -q
pytest -q
ruff check .
python -m compileall -q src app scripts tests
cd frontend && npm run build
```

测试覆盖：机组ID对应与匿名技术统计、场景操作员日期不符、摘要篡改/案例日期变更、已含证据无法覆盖、敏感字段不外泄、CLI严格0600/禁止重复输出，以及HTTP导入的422拒绝路径。

真正下一步仍是由有权限的操作者恢复学校官方PMSS会话，按同案例查询可用只读场景源，提供明确字段语义/单位的课程资料并追加不同日期的独立回测。
