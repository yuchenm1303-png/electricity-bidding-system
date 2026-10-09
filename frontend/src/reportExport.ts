import type { Report, Settings, RiskTrial, SingleTrial } from "./types";

/**
 * Standalone, offline-readable course demonstration report.
 * It describes ONLY the scenario that was actually sent to the local
 * teaching engine. It does not certify real PMSS settlement or submitted bids.
 * All user-controlled text is HTML-escaped before becoming markup.
 */
const escapeHtml = (value: unknown): string =>
  String(value ?? "—").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char] ?? char);

const num = (value: number | null | undefined, digits = 2): string =>
  value == null || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

const td = (value: unknown) => `<td>${escapeHtml(value)}</td>`;
const row = (cells: unknown[]) => `<tr>${cells.map(td).join("")}</tr>`;
const heading = (cells: string[]) => `<tr>${cells.map(x => `<th>${escapeHtml(x)}</th>`).join("")}</tr>`;

export function createStandaloneReportHtml(
  report: Report,
  analyzedSettings?: Settings | null,
): string {
  const risk = report.mode === "risk";
  const bestSingle = report.best as SingleTrial;
  const bestRisk = report.best as RiskTrial;
  const bestProfit = risk ? bestRisk.expected_profit : bestSingle.profit;
  const bestMw = risk ? bestRisk.expected_accepted_mw : bestSingle.accepted_mw;
  const sourceText = report.data_source === "synthetic" ? "教学仿真数据" : "来源声明：" + report.data_source;
  const generatedAt = new Date().toLocaleString("zh-CN", { hour12: false });

  const metrics = [
    ["推荐申报价", num(report.best.bid_price) + " / MWh"],
    [risk ? "预期期望利润" : "预计利润", num(bestProfit)],
    ["预计中标量", num(bestMw) + " MW"],
    ["已试算候选数", String(report.count)],
  ];
  const trialHeaders = risk
    ? ["报价", "期望利润", "下行利润", "最差利润", "中标 MW", "可行概率", "风险得分"]
    : ["报价", "出清价格", "中标 MW", "收入", "变动成本", "利润", "可行"];
  const trialRows: unknown[][] = risk
    ? (report.trials as RiskTrial[]).map(t => [
      num(t.bid_price), num(t.expected_profit), num(t.downside_profit),
      num(t.worst_profit), num(t.expected_accepted_mw),
      num(t.feasible_probability * 100, 1) + "%", num(t.score),
    ])
    : (report.trials as SingleTrial[]).map(t => [
      num(t.bid_price), num(t.clearing_price), num(t.accepted_mw),
      num(t.revenue), num(t.variable_cost), num(t.profit),
      t.feasible ? "是" : "否",
    ]);
  const parameterRows: unknown[][] = analyzedSettings ? [
    ["负荷", num(analyzedSettings.demand_mw) + " MW"],
    ["结算时段", num(analyzedSettings.interval_hours) + " h"],
    ["目标机组", analyzedSettings.target_unit_id],
    ["求解引擎", analyzedSettings.engine === "uniform" ? "单区域统一出清价" : "PyPSA 本地研究引擎"],
    ["报价搜索范围", `${num(analyzedSettings.start)} 至 ${num(analyzedSettings.stop)}，步长 ${num(analyzedSettings.step)}`],
    ["报价决策模式", risk ? "负荷与竞争报价压力情景" : "单场景报价搜索"],
    ...(risk ? [
      ["负荷不确定性", num(analyzedSettings.demand_uncertainty * 100, 0) + "%"],
      ["竞争报价不确定性", num(analyzedSettings.competitor_uncertainty * 100, 0) + "%"],
      ["风险厌恶系数", num(analyzedSettings.risk_aversion)],
      ["下行情景比例", num(analyzedSettings.tail_fraction * 100, 0) + "%"],
    ] : []),
  ] : [["参数来源", "未附带该次运行的参数快照；仅报告计算接口返回值"]];
  const offerRows: unknown[][] = analyzedSettings
    ? analyzedSettings.offers.map(o => [
      o.unit_id, num(o.quantity_mw) + " MW", num(o.bid_price),
      num(o.marginal_cost), o.unit_id === report.target_unit_id ? "是" : "否",
    ])
    : [];
  const outcomeRows: unknown[][] = risk
    ? bestRisk.outcomes.map(o => [
      o.name, num(o.probability * 100, 1) + "%",
      num(o.clearing_price), num(o.accepted_mw), num(o.profit),
      o.feasible ? "是" : "否",
    ])
    : [];

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PowerBid 报价策略分析报告 - ${escapeHtml(report.target_unit_id)}</title>
<style>
:root {font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;color:#19243d;background:#f3f5f9}
*{box-sizing:border-box}body{margin:0;padding:36px 18px}
main{max-width:1060px;margin:auto;background:white;padding:45px;border-radius:16px;box-shadow:0 18px 70px #1b274418}
header{border-bottom:2px solid #4355ac;padding-bottom:23px;margin-bottom:26px}
.eyebrow{color:#5062bd;font-size:12px;letter-spacing:.16em;font-weight:800}
h1{margin:12px 0 8px;font-size:31px}h2{margin:32px 0 12px;font-size:18px}
small,p{color:#566277;line-height:1.75}p{margin:8px 0}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.metric{border:1px solid #e3e8f3;background:#f7f9fe;padding:18px 14px;border-radius:12px}
.metric span{display:block;font-size:12px;color:#65718c}.metric strong{display:block;font-size:22px;overflow-wrap:anywhere;margin-top:7px}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:11px 10px;text-align:left;border-bottom:1px solid #e7eaf2}
th{background:#f5f7fb;color:#435274;font-weight:700}
.table-wrap{width:100%;overflow-x:auto}.notice{border-left:3px solid #7986d8;background:#f6f7fd;padding:12px 16px;margin-top:30px}
footer{color:#66748d;font-size:11px;border-top:1px solid #e2e7f0;margin-top:28px;padding-top:16px}
@media(max-width:700px){body{padding:0}main{padding:22px;border-radius:0}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.metric strong{font-size:18px}}
@media print{@page{size:A4;margin:15mm}body{background:white;padding:0}main{padding:0;box-shadow:none;max-width:none}h2{break-after:avoid}table{page-break-inside:auto}tr{break-inside:avoid}.metric{break-inside:avoid}.notice{break-inside:avoid}}
</style>
</head>
<body><main>
<header>
<div class="eyebrow">POWERBID STUDIO / COURSE SIMULATION</div>
<h1>电力市场报价策略分析报告</h1>
<p>${risk ? "风险压力情景分析" : "单场景报价优化"} · 目标机组：${escapeHtml(report.target_unit_id)} · 导出时间：${escapeHtml(generatedAt)}</p>
<p>数据：${escapeHtml(sourceText)}。这是本地模型的试算结果，不是老师 PMSS 平台的真实出清或结算。</p>
</header>
<div class="stats">${metrics.map(([key, value]) => `<div class="metric"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>
<h2>01 · 本次计算的市场参数</h2>
<div class="table-wrap"><table><tbody>${parameterRows.map(row).join("")}</tbody></table></div>
${offerRows.length ? `<h2>02 · 参与机组的申报信息</h2><div class="table-wrap"><table><thead>${heading(["机组编号", "申报容量", "当前申报价", "边际成本", "优化目标"])}</thead><tbody>${offerRows.map(row).join("")}</tbody></table></div>` : ""}
<h2>03 · 全部候选报价与计算结果</h2>
<div class="table-wrap"><table><thead>${heading(trialHeaders)}</thead><tbody>${trialRows.map(row).join("")}</tbody></table></div>
${risk ? `<h2>04 · 推荐报价的压力情景</h2><div class="table-wrap"><table><thead>${heading(["情景", "概率", "出清价", "中标 MW", "利润", "可行"])}</thead><tbody>${outcomeRows.map(row).join("")}</tbody></table></div>` : ""}
<div class="notice"><strong>结果说明</strong><p>所有推荐报价与利润均为计算模型在当前输入下的情景结果；不构成真实市场报价建议，不保证未来收益。与老师平台历史出清值的误差、机组爬坡、启停和节点网络约束等，不能通过本报告自动完成独立验证。请使用可信、脱敏数据进行研究。</p></div>
<footer>PowerBid Studio · 电力报价系统小组作业 · 本文件可离线打开，通过浏览器「打印 / 保存为 PDF」交付。</footer>
</main></body></html>`;
}

export function downloadStandaloneReport(
  report: Report,
  analyzedSettings?: Settings | null,
): void {
  const html = createStandaloneReportHtml(report, analyzedSettings);
  const url = URL.createObjectURL(
    new Blob([html], { type: "text/html;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `powerbid_${report.mode}_full_report.html`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
