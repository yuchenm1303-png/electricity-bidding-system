import { useState, type ChangeEvent } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { analyzePMSSJointCandidateMwh } from "./api";
import { numeric, type PMSSJointMwhRange } from "./types";

type Segment = {start_power: number; end_power: number; price: number};
const FIELD_UNITS: Record<string, string> = {
  min_mw:"MW", max_mw:"MW", ramp_up_mw:"MW/h", ramp_down_mw:"MW/h",
  startup_ramp_mw:"MW/transition", shutdown_ramp_mw:"MW/transition",
  min_up_hours:"h", min_down_hours:"h", startup_cost:"bid-cost/start",
  shutdown_cost:"bid-cost/stop", initial_on:"boolean", initial_mw:"MW",
  initial_state_hours:"h",
};

function makeLineageTemplate(
  snapshot: Record<string, unknown>, technical: Record<string, unknown>,
) {
  const units = Object.fromEntries(Object.entries(technical).map(([id, record]) => {
    const fields = record && typeof record === "object" && !Array.isArray(record)
      ? record as Record<string, unknown> : {};
    return [id, Object.fromEntries(
      Object.entries(FIELD_UNITS).map(([field, unit]) => [
        field, {value: fields[field] ?? null, unit, reference:""},
      ]),
    )];
  }));
  return {
    schema_version: 1, case_date: snapshot.caseDate,
    source_kind: "course_manual_user_attestation", units,
  };
}

function downloadTemplate(template: unknown) {
  const blob = new Blob([JSON.stringify(template, null, 2)], {type:"application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "powerbid_uc_field_source_template.json";
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PMSSJointMwhPanel({
  snapshot, target, candidate, planLabel, disabled,
}: {
  snapshot: Record<string, unknown>;
  target: string;
  candidate: Segment[];
  planLabel: string;
  disabled: boolean;
}) {
  const [physical, setPhysical] = useState<Record<string, unknown> | null>(null);
  const [physicalName, setPhysicalName] = useState("");
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null);
  const [lineageName, setLineageName] = useState("");
  const [source, setSource] = useState("");
  const [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [range, setRange] = useState<PMSSJointMwhRange | null>(null);

  async function loadEvidence(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    setPhysical(null);
    setPhysicalName("");
    setLineage(null);
    setLineageName("");
    setRange(null);
    setAttested(false);
    setError("");
    if (!file) return;
    if (file.size > 100_000) {
      setError("技术参数文件超过100KB，请只导入逐机组的必要技术字段");
      return;
    }
    try {
      const data: unknown = JSON.parse(await file.text());
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("逐机组技术参数必须是按机组ID索引的JSON对象");
      }
      setPhysical(data as Record<string, unknown>);
      setPhysicalName(file.name);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "JSON参数读取失败");
    }
  }

  async function loadLineage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    setLineage(null);
    setLineageName("");
    setRange(null);
    setAttested(false);
    setError("");
    if (!file) return;
    if (file.size > 150_000) {
      setError("逐字段来源清单超过150KB；请只保留每个参数的值、单位和课程出处");
      return;
    }
    try {
      const data: unknown = JSON.parse(await file.text());
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("逐字段来源清单必须是JSON对象");
      }
      setLineage(data as Record<string, unknown>);
      setLineageName(file.name);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "逐字段来源清单读取失败");
    }
  }

  async function run() {
    if (!physical || !lineage || !candidate.length || !source.trim() || !attested ||
        !target || busy || disabled) return;
    setBusy(true);
    setRange(null);
    setError("");
    try {
      const result = await analyzePMSSJointCandidateMwh(
        snapshot, target, candidate, physical, lineage, source.trim(),
      );
      if (result.target_unit_id !== target ||
          result.minimum_24h_dispatch_mw.length !== 24 ||
          result.maximum_24h_dispatch_mw.length !== 24 ||
          result.safe_for_live_submission !== false ||
          result.counterfactual_pmss_verified !== false ||
          result.independent_pmss_technical_verification !== false ||
          result.uses_historical_outcomes_as_forecast !== false ||
          result.technical_lineage_audit?.user_source_attested !== true ||
          result.technical_lineage_audit?.independent_pmss_semantics_verified !== false ||
          result.pmss_write_performed !== false ||
          result.pmss_clearing_executed !== false) {
        throw new Error("联合优化接口返回研究范围外的状态，拒绝展示");
      }
      setRange(result);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "联合求解失败");
    } finally {
      setBusy(false);
    }
  }

  const rows = range ? range.minimum_24h_dispatch_mw.map((minimum, idx) => ({
    period: idx + 1,
    leastDay: minimum,
    mostDay: range.maximum_24h_dispatch_mw[idx],
  })) : [];

  return <div className="pmss-panel">
    <div className="pmss-panel-head">
      <div>
        <small>PHYSICAL / OPTIONAL VERIFIED INPUT</small>
        <h3>24小时联合机组约束 · 全日中标电量范围</h3>
        <p>区别于上方独立小时 DC 区间：这里联合求解机组启停、爬坡、
          最短开停机与网络线路约束，并在近似最低总申报成本下分别计算全天最少、最多中标 MWh。</p>
      </div>
      <span className="pmss-state-label"><ShieldCheck size={14}/> 独立核实参数后使用</span>
    </div>
    <div className="pmss-error" role="status">
      老师PMSS当前技术参数语义尚未独立证实，不能把历史容量、
      中标曲线或平台只读技术字段自动填成启停/爬坡参数。
      请只在掌握课程资料且能够逐台核实参数时主动导入。
    </div>
    <div className="pmss-controls">
      <label>逐机组技术参数 JSON（所有机组完整字段）
        <input type="file" accept=".json,application/json" disabled={busy || disabled}
          onChange={event => void loadEvidence(event)}
          aria-label="导入自行核实的逐机组技术参数JSON"/>
      </label>
      <label>课程逐字段来源清单 JSON（必须和上方数值一致）
        <input type="file" accept=".json,application/json" disabled={busy || disabled}
          onChange={event => void loadLineage(event)}
          aria-label="导入逐台逐字段数值与课程出处的JSON审核清单"/>
      </label>
      <label>课程参数核实来源（必填）
        <input type="text" maxLength={500} value={source}
          disabled={busy || disabled} placeholder="如：课程实验手册第X章、参数日期和单位"
          onChange={event => {
            setSource(event.target.value);
            setRange(null);
            setAttested(false);
          }}/>
      </label>
    </div>
    {physicalName && <p className="pmss-footnote">
      已导入参数文件：{physicalName}。仅保存于当前页面内存，并随本次研究请求发送同源后端。
    </p>}
    {physical && <div className="pmss-toolbar">
      <p>先下载逐字段来源模板，为每个机组的13个参数填写手册章节、页码及版本。空白引用无法通过审核。</p>
      <button className="pmss-run-button" type="button" disabled={busy || disabled}
        onClick={() => downloadTemplate(makeLineageTemplate(snapshot, physical))}>
        下载字段来源模板
      </button>
    </div>}
    {lineageName && <p className="pmss-footnote">
      已导入来源清单：{lineageName}。计算前逐台核验单位、数值及对应案例日期；
      课程引用由您提供，PowerBid不自动认证手册真实性。
    </p>}
    <label className="pmss-footnote">
      <input type="checkbox" checked={attested} disabled={!physical || !lineage || busy || disabled}
        onChange={event => {setAttested(event.target.checked);setRange(null);}}/>
      我已经逐台核实机组初始状态、出力、开停机时长、爬坡、启停成本及相关单位；
      知道本研究仍不是PMSS实际结算和新报价验证。
    </label>
    <div className="pmss-toolbar">
      <p>候选来源：{planLabel}。不导入完整可信参数时，联合物理研究保持锁定。</p>
      <button type="button" className="pmss-run-button"
        disabled={!physical || !lineage || !attested || !source.trim() || busy || disabled}
        onClick={() => void run()}>
        {busy ? "正在求解联合24小时两种极值方案…" : "运行24小时联合电量区间"}
        <ArrowRight size={16}/>
      </button>
    </div>
    {error && <div className="pmss-error" role="alert">{error}</div>}
    {range && <>
      <p className="pmss-footnote">
        已审核{range.technical_lineage_audit?.attested_fields ?? 0}项逐字段来源记录：
        引用与计算数值相同，但这仍不是老师PMSS实际机组语义与单位的独立认证。
      </p>
      <div className="pmss-summary" aria-label="联合24小时出力方案">
        <article className="pmss-metric">
          <span>全天最少中标量</span>
          <strong>{numeric(range.minimum_accepted_mwh, 2)} MWh</strong>
          <small>完整联合约束下的一套调度</small>
        </article>
        <article className="pmss-metric">
          <span>全天最多中标量</span>
          <strong>{numeric(range.maximum_accepted_mwh, 2)} MWh</strong>
          <small>可能采用不同机组开停状态</small>
        </article>
        <article className="pmss-metric">
          <span>最优成本允许偏差</span>
          <strong>{numeric(range.allowed_primary_cost_increase, 5)}</strong>
          <small>包含启动/停机成本</small>
        </article>
      </div>
      <div className="pmss-chart" role="img"
        aria-label="不同全日目标下两个物理可行方案的24小时调度比较">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{top:14,right:16,bottom:5,left:-8}}>
            <CartesianGrid stroke="var(--ta-border)" strokeDasharray="4 5" vertical={false}/>
            <XAxis dataKey="period" tick={{fill:"var(--ta-muted)",fontSize:11}}
              tickLine={false} axisLine={false}/>
            <YAxis tick={{fill:"var(--ta-muted)",fontSize:11}}
              tickLine={false} axisLine={false}/>
            <Tooltip contentStyle={{
              background:"var(--ta-panel)",color:"var(--ta-ink)",
              border:"1px solid var(--ta-border)",borderRadius:11,
            }}/>
            <Legend verticalAlign="top" height={32}/>
            <Line dataKey="leastDay" name="全天电量最少方案的逐时MW"
              stroke="#039855" strokeWidth={2.4} dot={false} isAnimationActive={false}/>
            <Line dataKey="mostDay" name="全天电量最多方案的逐时MW"
              stroke="#465fff" strokeWidth={2.4} dot={false} isAnimationActive={false}/>
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="pmss-footnote">
        注意：两条曲线分别代表全天电量极小/极大的完整可行调度，
        不是每个小时独立的最小/最大MW包络。两条曲线在某些时段可以交叉。
      </p>
      <p className="pmss-footnote">
        技术参数来源由上传者声明，不代表PowerBid已独立验证老师实际设备数值。
        保留了全网直流潮流、24小时启停与爬坡约束，但未包含网损、备用、
        AC电压与PMSS特有结算机制。本报告不提供真实利润或可提交报价的认证。
      </p>
    </>}
  </div>;
}
