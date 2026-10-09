# 第二十二阶段：生产前后端功能配对验收（只读）

## 真实线上核查结论（2026-10-09）

正式站点 https://power.smirel.com/ 当前可访问，`GET /api/health` 返回正常状态。此前根据首页主JS `index-BS8MrSnV.js` 未包含文本`holdout-gate`得出“前端尚未部署”的初步推断**并不成立**：React/Vite会对工作台进行**动态模块拆分**，真正的匿名历史留出审核页面位于独立的 `WorkspaceEntry-*.js`。

在正式网站当前的受Caddy代理保护的容器中，已经确认：
- `WorkspaceEntry-*.js` 含有`holdout-gate`与`历史分配规则`，网页审核面板确已出现在静态资源中；
- FastAPI `/openapi.json`包含`POST /api/pmss/holdout-gate`，该路径在服务器上真实存在；
- **向该只读分析端点发送明确无效的 `{"report":{}}`**，服务返回预期422，表明会拒绝错误的历史报告，而不是自动认可或错误触发其他流程；
- `GET`请求POST-only接口不是正确的健康检测方式。此前一次404探测也不是该功能缺失的证据。

这证明线上当前**用户可访问的 JS 静态资源包含新面板，后端具有同名只读审核能力**。它不等于自动化浏览器点开面板的所有交互均已完成端到端验收，也不证明准确部署了某个Git提交；`productionMainHeadVerified=false`会明确说明Git版本并未通过这个检测认证。

## 新增可重复的发布验收

`scripts/smoke_powerbid_release.py`采用Python标准库，不读取任何私人用户凭据，不进入老师的PMSS域名。它在一个明确的PowerBid公网站点执行如下受限步骤：

1. 校验HTTPS源站，拒绝含用户密码、查询参数、路径、片段的非法URL；只允许开发本地使用HTTP；
2. GET首页HTML，从Vite模块入口出发，**递归扫描同源允许的 `/assets/*.js` 与动态导入引用**（最多24个、单响应最多4MB），直到同时发现历史审核路由与面板文字；不会因为它们不在首页JS内便报错；
3. GET `/api/health`，检查正确的正常状态；
4. GET `/openapi.json`，检查是否显式声明了该分析接口的POST方法；
5. 唯一一次POST发送固定无效聚合内容`{"report":{}}`，预期422。**不会**发送真实数据、Cookie、报价或请求任何老师PMSS接口。

失败时输出统一 `DEPLOYMENT_PARITY_UNVERIFIED` 并返回非0退出码，不输出可能包含认证细节的服务器响应内容；成功输出 `FRONTEND_BACKEND_HOLDOUT_PARITY_VERIFIED` 与各检查项的结果。结果明确包含`teacherPMSSAuthenticated=false`、`originalHistoricalInputsInspected=false`、`submittedMarketBid=false`、`executedTeacherClearing=false`。

本工具验证功能**发布配对**，不是PMSS真实校准和出清验证，也不是新报价收益承诺。

### 本地/可信服务器复查

```bash
python scripts/smoke_powerbid_release.py --origin https://power.smirel.com
```

本阶段首次在生产网站执行的真实检查返回：
```json
{
  "state": "FRONTEND_BACKEND_HOLDOUT_PARITY_VERIFIED",
  "frontendLazyChunkDiscovered": true,
  "frontendHistoryGatePresent": true,
  "backendPostRoutePresent": true,
  "invalidResearchReportRejected": true,
  "productionMainHeadVerified": false,
  "teacherPMSSAuthenticated": false,
  "originalHistoricalInputsInspected": false,
  "submittedMarketBid": false,
  "executedTeacherClearing": false
}
```

在 GitHub Actions 页面，也可以手动启动`PowerBid Production Parity Smoke`。此工作流**不会对每个尚未部署的PR自动触发**，以免出现“PR代码比生产更新”时错误阻塞正常开发；正式发布后手动执行即可。

## 与其它UI窗口的协作约束

已有其它开发窗口正在恢复/优化 Loom 原版液态玻璃鼠标，生产Caddy路由实际转发到 `powerbid-studio-live-native-shader-ea0ab81`。本阶段**没有**重建/替换这个Docker容器、没有覆盖已有静态页面资源、没有修改Caddy路由或原版鼠标折射代码。真实线上功能验证通过后，也就不需要为了修复不存在的“历史审核前端缺失”去重发可能过时的UI包。

## 测试范围

`tests/test_powerbid_release_smoke.py`对合法Lazy Chunk、错误入口、JS缺失、后端404/错误成功码、错误健康状态、缺失POST规范及非法源站/资产路径全部采用本地合成响应测试。真实生产外部访问只在明确执行发布验收脚本时发生，不是日常单元测试的网络依赖。
