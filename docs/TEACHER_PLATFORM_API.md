# 老师 PMSS 平台对接记录

本页只记录已经通过实际网页会话确认的接口与字段，不保存账号、密码、Cookie、Token 或课程项目 ID。

## 已确认的链路

工程列表
→ 案例 / 日期
→ 市场规则与 scopeId
→ 电网 / 机组数据
→ 读取或提交机组分段报价
→ 执行出清
→ 读取收敛状态、机组中标、节点电价、支路潮流

## 工程与场景

- GET /pmss/web/project/list
- GET /pmss/web/project/listSimulateCaseByProjectId
- GET /pmss/web/tmScene/getMarketSystemAndScopIds
- GET /pmss/web/powerModel/getPowerModel
- POST /pmss/web/tmScene/spot/unit/getUnitDictTreeFilterByTypesWithMva

机组树中已经确认可以获得机组 ID / 名称、额定容量 mvarate、最大最小可调出力、机组类型和 runningCost。

市场规则接口已经确认可以获得日前 / 实时市场、报价段数、价格边界、24 时段配置和每天对应的 scopeId。

## 分段报价

读取：

- GET /pmss/web/tmScene/spot/unit/electricEnergy

保存：

- POST /pmss/web/tmScene/spot/unit/electricEnergy

网页保存时的核心 JSON 结构已经确认，包括 scopeId、unitId、24 时段、启动成本和 segmentDatas 分段报价数组。

TeacherPlatformAdapter 默认不会写入平台；调用 save_unit_bid(..., commit=True) 才会真正提交。

## 出清

执行：

- POST /pmss/web/simulate/execute

通过浏览器网络拦截确认，请求体只需要 caseId 与 comment。

读取优化状态：

- GET /pmss/web/simulate/getClearingResult?caseId=...&marketTypeAtom=DA
- GET /pmss/web/simulate/getClearingResult?caseId=...&marketTypeAtom=RT

返回结果中已经确认有 isConverge、isRelax、relaxNum、iters、totalCost、totalRunCost、totalStartCost。

run_clearing(..., commit=True) 才会实际触发出清。

## 结果读取

市场概览：

- GET /pmss/web/marketResult/resultOverView/getResultOverViewForGd

机组中标：

- GET /pmss/web/marketResult/unitBid/getSelectTree
- POST /pmss/web/marketResult/unitBid/listForGd

节点电价：

- GET /pmss/web/marketResult/nodalLmp/getSelectTree
- POST /pmss/web/marketResult/nodalLmp/list

支路潮流：

- GET /pmss/web/marketResult/branchFlow/getSelectTree
- POST /pmss/web/marketResult/branchFlow/list

机组中标结果已经确认包含 24 时段中标出力、出清价格和机组收入。支路结果已经确认包含支路潮流、首末端节点电价、影子价格和阻塞盈余。

## 当前边界

这套 API 是课程教学平台的内部接口，并非公开稳定 API。软件应通过 Adapter 隔离字段变化，不能让 UI 或报价算法直接依赖网页内部实现。

平台现有数据里出现过规则接口价格上界与已保存机组报价数值不一致的情况，因此现阶段不要擅自把规则字段当成唯一校验真值。提交前应同时参考网页实际校验逻辑和课程要求。
