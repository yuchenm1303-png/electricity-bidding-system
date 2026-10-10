# PMSS 标准模型导入（只读、按案例绑定）

目的：在可信服务器上，把已经授权读取的 PMSS 39 Bus、46 线路、10 机组、24 时段节点负荷、日前报价规则、历史五段报价、历史出清结果与可获得的机组约束证据整理成 **私有、可校验、可复用的标准数据结构**。本功能复用现有模块，不复制老师平台、不触发重新出清。

## 现成能力（不重新造轮子）

- 网络：powerbid.pmss_grid_bridge.sanitize_pmss_network → 现有 network_dispatch/network_strategy。
- 机组、曲线、市场规则：powerbid.pmss_integration.snapshot_from_pmss。
- 24 小时场景节点负荷：powerbid.pmss_load.parse_da_nodal_loads 与 PMSS 场景导出器。
- 历史机组出清、节点电价、支路潮流：powerbid.pmss_result_loader 与现有解析器；兼容旧版原生字段和新版归一化字段。
- 匿名计算开关与机组初始输入 **仅做证据摘要**：powerbid.pmss_scene_constraint_evidence，不能据此解锁 UC 物理模型。

新增接口：

- Python：powerbid.pmss_model_import.build_standard_pmss_model(source_snapshot, private_grid, grid_case_date=...)。
- 可信主机实时只读：read_live_standard_pmss_model(adapter, context, case, private_grid, grid_case_date=...)。
- CLI：scripts/import_pmss_model.py（不会更新老师平台，也不会读取任何写入路由）。

## 私有服务器导入方法

已有授权只读导出及受控网架的**离线导入**：

    python scripts/import_pmss_model.py \
      --snapshot /private/pmss-day-ahead-case.json \
      --grid /private/pmss-grid.json \
      --grid-case-date 2025-09-01 \
      --output /private/pmss-standard-case.json

从已有只读 PMSS 连接直接读取所选案例：

    PMSS_BASE_URL=<set-privately> PMSS_COOKIE_FILE=<set-privately> \
    PMSS_PROJECT_ID=<set-privately> \
    python scripts/import_pmss_model.py \
      --live --case-date 2025-09-01 \
      --grid /private/pmss-grid.json \
      --grid-case-date 2025-09-01 \
      --output /private/pmss-standard-live.json

- 命令中的环境变量只是名称占位符。实际凭据必须通过私有运行环境注入，不能写入命令日志、文档、Git 或前端；绝不要求上传老师的 Cookie。
- 实时读取复用 TeacherPlatformAdapter：读取项目、市场规则、机组、24 小时场景负荷、历史报价/出清、机组计算规则和初始状态；只查询明确的现有只读端点（有些查询采用 HTTP POST，但语义为只读查询）。
- 不想读取额外的匿名机组约束证据时可用 --skip-scene-evidence。离线模式可附加 --scene-evidence /private/aggregate.json，必须通过现有证据验证器。
- 网架 JSON 本身缺少经过认证的案例日期绑定，所以必须显式指定 --grid-case-date 与 --case-date 或原始快照中的 caseDate 一致。同日不自动证明文件同源；必须由服务器导出操作者核对。
- 输出必须在**任何 Git 工作区之外**且尚不存在；仅写本机 0600 文件，绝不覆盖旧证据。输出数据是私有的，**禁止 commit、上传公网前端或以公共 API 返回**。

## 结构与校验清单

schemaVersion = powerbid.pmss.standard.v1。模型沿用既有应用可消费的 unitTree、unitBids、marketSystem、demandForecastMw、dcNetwork、results 字段，并补充：

- caseDate / marketTypeAtom=DA / periodNum=24：历史案例边界。
- units：有功与出力 MW；线路相对电抗 p.u.；baseMva=1 仅用于本地 DC 模型计算归一化，不代表真实系统容量基准。价格/费用单位在未经独立核对前明确标记为源平台口径未验证。
- dcNetwork：39 节点、46 支路、10 机组接入节点、39×24 小时节点负荷。验证线路两端、机组所在节点、无重复 ID、线路变比为 1、负荷逐时合计与源场景一致。
- unitTree/unitBids/marketSystem：10 机组报价容量与成本、各 24 小时报价曲线、日前五段及允许报价范围。历史数据不因与**当前**规则边界有冲突而被改写；冲突条数只记录在 importValidation.historicalPriceRuleBoundWarnings。
- results：10×24 机组中标功率/价格/收入、39×24 节点电价、46×24 支路潮流、端点电价、影子价格与拥塞盈余；拒绝缺小时、非有限数值、重复/未知 element ID 和市场类型混用。
- generatorConstraints：10 机组的**报价侧出力区间**和可选的**匿名、只读场景开关/初始输入统计**。禁止把这些编码解释成已经核实的爬坡率、最短启停时间、机组初始运行状态或实际 SCUC 约束。physicalUCVerified 与 jointMilpReady 始终为 false。
- importValidation：数据覆盖量、完整性与明确的未验证项；不宣称与 PMSS AC/SCUC 真实出清和结算一致。

## 边界与待补证据

已迁移到标准模型的是**可访问并核对的单个历史日前案例**。如要覆盖全部老师课程案例日期，需在授权状态下分别导出并按日期绑定逐个核验；不能复用另一日期网架或负荷假装同案例。

尚需老师平台的文档、明确的业务字段含义或正式授权实验：机组爬坡率和单位 MW/h、最短开停机小时、初始状态编码、启动/停机过渡和费用、场景开关反向/三态语义；RT 市场、物理 baseMVA、完整市场清算规则、出清价格单位和结算口径、PMSS 真正重出清结果。没有这些证据，不启用“与老师平台完全一致”的模型声明。

验证建议：

    PYTHONPATH=src python -m unittest discover -s tests -p 'test_pmss_model_import.py' -v

本仓库测试只使用合成样本；真数据验证仅在有权限的服务器私有目录执行，不能把原数据作为 Git 测试夹具。
