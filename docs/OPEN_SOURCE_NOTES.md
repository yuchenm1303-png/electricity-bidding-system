# Open-source reference notes

PowerBid Lab 的目标不是复刻下面这些项目，而是明确“哪些成熟能力应该复用，哪些才是我们需要自己做的”。

## PyPSA

- Repository: https://github.com/PyPSA/PyPSA
- Docs: https://docs.pypsa.org/
- 适合复用：电网组件、经济调度、线性最优潮流、市场出清、节点边际价格、机组组合等。
- 当前项目用途：作为可替换的成熟出清/网络计算内核。

PyPSA 官方已经提供 Demand and Supply Bids、Electricity Markets 等示例。我们没有复制其源码，只通过公开 API 做 Adapter。

## ASSUME

- Repository: https://github.com/assume-framework/assume
- Docs: https://assume.readthedocs.io/
- 适合参考：Unit Operator、Bidding Strategy、Market 的分层，以及从市场状态生成报价的策略接口。
- 当前项目用途：参考报价策略架构；后期考虑对接高级策略或强化学习实验。

ASSUME 的策略核心思想是把“机组状态与市场信息”映射成报价，这与本项目后续的 Strategy 层高度一致。

## AMES

- Repository: https://github.com/ames-market/AMES-V5.0
- 适合参考：日前/实时市场、发电商行为、SCUC/SCED、节点边际价格以及完整批发市场业务流程。
- 当前项目用途：流程与课程研究参考，不作为第一版代码底座。

## OpenEUPHEMIA

- Repository: https://github.com/rebase-energy/OpenEUPHEMIA
- 适合参考：真实日前市场复杂出清规则的开放实现。
- 当前项目用途：后期研究复杂订单与真实市场规则，不加入 MVP。

## POMATO

- Repository: https://github.com/richard-weinhold/pomato
- 适合参考：电力市场、网络安全约束、再调度和 Flow-Based Market Coupling。
- 当前项目用途：复杂网络市场研究参考。

## 本项目边界

第一版只自己实现：

1. 统一的数据模型；
2. 报价候选生成与优化；
3. 收益/风险评价；
4. 外部市场 Adapter；
5. 面向课程演示的 UI。

不会自己重写：

- 大规模 OPF 求解器；
- 完整 SCUC/SCED；
- 复杂潮流算法；
- 成熟优化器。

这些能力优先通过 PyPSA 等成熟项目复用。
