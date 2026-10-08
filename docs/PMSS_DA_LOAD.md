# PMSS 24 时段日前负荷接口

已在授权浏览器会话中按网页真实调用结构验证：

- 请求：POST /pmss/web/scene/loadFc/list
- JSON body：ids 为空数组，pageNo 为1，pageSize 为999，sceneId 与 sceneDateKey 来自所选案例的 pmSceneId 和 pmSceneDateKey。
- 响应：data.periodNum=24、data.data.rowCount=39、data.data.datas 长度40。
- 特别注意：第一条为「统调负荷」汇总，后面39条为 Bus1–Bus39 的节点负荷。不能将这40条直接求和。
- 节点日前曲线：每条 data.data.datas[i].da.t01 … da.t24。
- 本案例「统调负荷」24小时序列与39节点逐时段相加完全一致。

2025-09-01 场景校验：

- 最高日前负荷：6267.01 MW
- 最低日前负荷：3605.25 MW
- 24小时平均：5157.858 MW，与 PMSS 已有概览一致。

代码：src/powerbid/pmss_load.py、TeacherPlatformAdapter.get_da_nodal_loads、pmss_export.build_da_scene_snapshot。

安全边界：

- 接口为查询-only POST，不是写入。
- 负荷属于历史教学场景中的**日前负荷输入**，可用于此场景的回测；它不是对未来任意日期的预测。
- 快照将显式标记 historicalBacktestOnly=true，且不包含账号、密码、Cookie、Token 或工程的私有 caseId/scopeId。
- 五段报价推荐仍由 PowerBid 单区域教学模型计算，并没有向老师 PMSS 提交报价或运行真实重出清。
