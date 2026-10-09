## 账号系统（可选部署）

独立开发中的登录 / 注册 / 管理员账号方案详见 [账号系统部署与安全说明](docs/ACCOUNT_SYSTEM.md)。
默认不启用账号拦截，现有 PMSS 教学与报价工作台不会突然需要登录。
必须先挂载持久化目录并通过服务器交互命令初始化管理员，再考虑正式开启。

# PowerBid Lab

面向电力市场研讨与教学实验的 **发电商报价决策原型系统**。

我们不从零重写完整电力市场，而是把项目拆成：

```text
市场/机组数据
    ↓
报价决策层（本项目重点）
    ↓
候选报价 → 出清 → 收益评价 → 推荐报价
    ↓
可替换的市场出清环境
    ├─ 内置教学引擎
    ├─ PyPSA
    └─ 老师的报价出清仿真系统（接口已联调）
```

> 当前版本是课程研讨 MVP，不是生产级交易系统。`data/sample_market.json` 明确标记为仿真数据。

## 网页首页与工作台

本项目的 React 网站使用同一个构建产物、两个独立入口：

- `/`：PowerBid Lab 数字艺术首页（品牌展示、原创交互式三维电网星座（旋转、节点点选、示意能量轨迹）、交互式报价示意）。
- `/app`：原有报价研究工作台，继续调用 FastAPI `/api/*` 接口。

首页的报价探索器仅用于交互视觉演示，**不构成真实优化、实时交易或交易建议**；实际模拟需进入 `/app`。桌面端 Streamlit 启动器与策略、PMSS 接口无需改变。

本地前端开发：`cd frontend && npm ci && npm run dev`，打开 `http://localhost:5173/` 查看首页、`http://localhost:5173/app` 查看工作台。构建时通过 `VITE_BASE` 适配子路径部署。首页与工作台按需分包，并支持 `prefers-reduced-motion`。

## 已完成

- [x] 统一的机组报价 / 市场场景数据模型
- [x] 单区域统一出清价（uniform-price）教学引擎
- [x] 同价边际机组按容量比例分配
- [x] 网格搜索候选报价
- [x] 按真实边际成本计算收入、成本、利润
- [x] 不确定性压力测试：负荷与竞争者报价波动
- [x] 风险厌恶报价优化：期望利润 + 下行情景利润
- [x] 场景数据来源标记（platform / course / public / synthetic）
- [x] Streamlit 可视化演示界面
- [x] 单场景与风险分析结果 CSV 导出
- [x] PyPSA 可选出清 Adapter
- [x] 老师 PMSS 平台 Adapter：工程 / 机组 / 报价 / 出清 / 结果读取
- [x] 示例仿真场景
- [x] 单元测试与 GitHub Actions CI
- [x] 开源项目参考与架构说明

## 当前软件到底在算什么

目标机组的 `bid_price`（向市场报的价格）和 `marginal_cost`（真实发电边际成本）分开保存。

单场景模式会依次尝试：

```text
180 → 出清 → 中标电量 → 利润
190 → 出清 → 中标电量 → 利润
200 → 出清 → 中标电量 → 利润
...
390 → 出清 → 中标电量 → 利润
400 → 出清 → 中标电量 → 利润
```

统一价市场下，当前 MVP 用下面的单时段结算关系：

```text
利润 = (统一出清价 - 真实边际成本) × 中标MW × 时段小时数
```

风险分析模式会进一步生成“负荷高/中/低 × 竞争报价高/中/低”的透明压力情景，让同一个候选报价在多种市场状态下重新出清，再同时比较：

- 期望利润；
- 下行情景平均利润；
- 最差情景利润；
- 预计中标量；
- 市场可行概率。

风险得分采用可解释的线性组合：

```text
风险得分
= (1 - 风险厌恶系数) × 期望利润
+ 风险厌恶系数 × 下行情景利润
```

这一步是敏感性/压力测试，不是假装已经拥有真实市场预测能力。

## 快速运行

要求 Python 3.11+。

### 1. 命令行 MVP

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e '.[dev]'

powerbid data/sample_market.json --start 180 --stop 400 --step 10
```

### 2. 可视化界面

```bash
pip install -e '.[ui]'
streamlit run app/streamlit_app.py
```

界面里可以直接修改：

- 市场负荷；
- 目标机组；
- 各机组申报容量；
- 竞争机组报价；
- 真实边际成本；
- 候选报价范围和步长；
- 负荷与竞争报价波动范围；
- 风险厌恶程度。

然后点击“开始搜索推荐报价”，即可查看推荐报价、收益/风险曲线、各压力情景结果，并可导出 CSV。

### 3. 用 PyPSA 做出清

```bash
pip install -e '.[pypsa]'
powerbid data/sample_market.json --engine pypsa --start 180 --stop 400 --step 10
```

当前 PyPSA Adapter 先实现单市场区。等老师网页字段确认后，再加入 Bus、Line、电抗、线路容量等网络数据。

## 为什么不是从零做

我们把成熟开源项目当作不同层的参考或计算内核：

- **PyPSA**：网络、经济调度、最优潮流、市场出清、节点边际价格；
- **ASSUME**：Unit / Bidding Strategy / Market 的分层与策略设计；
- **AMES**：日前/实时市场、SCUC/SCED、LMP 等完整批发市场流程；
- **OpenEUPHEMIA / POMATO**：复杂真实市场规则与网络市场研究参考。

详细记录见 [`docs/OPEN_SOURCE_NOTES.md`](docs/OPEN_SOURCE_NOTES.md)。

## 项目结构

```text
.
├── app/
│   └── streamlit_app.py          # 课堂演示 UI
├── data/
│   └── sample_market.json        # 明确标注的仿真场景
├── docs/
│   ├── ARCHITECTURE.md           # 架构、数据来源和后续计划
│   ├── DECISION_MODEL.md         # 报价输入、数据来源与风险模型
│   └── OPEN_SOURCE_NOTES.md      # 成熟开源项目参考
├── src/powerbid/
│   ├── adapters/
│   │   └── pypsa_engine.py       # PyPSA Adapter
│   ├── clearing/
│   │   ├── base.py               # ClearingEngine 接口
│   │   └── uniform_price.py      # 内置教学出清引擎
│   ├── cli.py
│   ├── models.py
│   ├── optimizer.py
│   ├── risk.py                   # 压力情景与风险报价优化
│   ├── scenario_io.py
│   └── settlement.py
└── tests/
```

## 数据从哪里来

后续场景都要记录数据来源，不能把人为构造数据冒充真实市场数据：

- `platform`：老师仿真系统/API/导出；
- `course`：课程材料；
- `public`：公开市场数据；
- `synthetic`：我们人为构造的教学或压力测试场景；
- `unknown`：来源尚未确认。

现在的示例属于 synthetic。老师平台内部 API 已完成首轮联调，TeacherPlatformAdapter 已加入代码库；接口记录见 docs/TEACHER_PLATFORM_API.md。

## 下一阶段

1. 根据老师仿真网页的真实字段建立数据映射；
2. 加入 Bus / Line / reactance / transmission limit；
3. 用 PyPSA 做带网络约束的市场出清；
4. 加入 24h 多时段负荷、风光和机组运行约束；
5. 接历史价格、竞争者行为和真实概率场景；
6. 再研究 ASSUME / 强化学习报价策略。

详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 和 [`docs/DECISION_MODEL.md`](docs/DECISION_MODEL.md)。

## License

MIT
