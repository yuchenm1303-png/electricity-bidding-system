import { useEffect, useMemo, useState } from "react";
import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender, createColumnHelper, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Plus, Search, Trash2, Download, Check, AlertCircle } from "lucide-react";
import type { Offer } from "./types";
import { numeric, csvExport } from "./types";

type Props = {
  offers: Offer[];
  targetId: string;
  onChange: (offers: Offer[]) => void;
  onTarget: (unitId: string) => void;
  expanded?: boolean;
};
type Field = keyof Offer;

function CellEditor({ value, kind, onCommit, title }: {
  value: string | number; kind: "text" | "number";
  onCommit: (value: string | number) => void;
  title: string;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    if (kind === "text") {
      const next = text.trim();
      if (next) onCommit(next);
      else setText(String(value));
    } else {
      const next = Number(text);
      if (text.trim() && Number.isFinite(next) && next >= 0) onCommit(next);
      else setText(String(value));
    }
  };
  return <input
    className={"cell-editor " + (kind === "number" ? "is-number" : "")}
    type={kind === "number" ? "number" : "text"}
    min={kind === "number" ? "0" : undefined}
    step={kind === "number" ? "any" : undefined}
    aria-label={title} title="直接编辑"
    value={text} onChange={e => setText(e.target.value)}
    onClick={e => e.stopPropagation()}
    onBlur={commit}
    onKeyDown={e => {
      if (e.key === "Enter") e.currentTarget.blur();
      if (e.key === "Escape") { setText(String(value)); e.currentTarget.blur(); }
    }}
  />;
}

const columnHelper = createColumnHelper<Offer>();
export function UnitsTable({ offers, targetId, onChange, onTarget, expanded = false }: Props) {
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [warning, setWarning] = useState("");
  const update = (originalId: string, field: Field, value: string | number) => {
    if (field === "unit_id" && value !== originalId && offers.some(o => o.unit_id === value)) {
      setWarning("机组编号不能重复"); return;
    }
    setWarning("");
    onChange(offers.map(o => o.unit_id === originalId ? { ...o, [field]: value } : o));
    if (field === "unit_id" && targetId === originalId) onTarget(String(value));
  };
  const remove = (id: string) => {
    if (offers.length < 2) { setWarning("至少需要保留一台机组"); return; }
    const next = offers.filter(o => o.unit_id !== id);
    onChange(next);
    if (id === targetId) onTarget(next[0].unit_id);
  };
  const columns = useMemo(() => [
    columnHelper.display({
      id: "target",
      header: () => <span className="table-hint">目标</span>,
      cell: info => <button
        type="button" className={"target-radio " + (info.row.original.unit_id === targetId ? "selected" : "")}
        onClick={() => onTarget(info.row.original.unit_id)}
        aria-label={"设 " + info.row.original.unit_id + " 为目标机组"}
        title="设为本轮优化目标"
      >{info.row.original.unit_id === targetId && <Check size={11}/>}</button>,
      size: 62,
    }),
    columnHelper.accessor("unit_id", {
      header: "机组编号", cell: info => <div className="unit-identity">
        <span className="unit-symbol">{info.row.original.unit_id.slice(0, 2).toUpperCase()}</span>
        <CellEditor value={info.getValue()} kind="text"
          title={info.getValue() + " 的编号"}
          onCommit={v => update(info.row.original.unit_id, "unit_id", v)}/>
      </div>, size: 160,
    }),
    columnHelper.accessor("quantity_mw", {
      header: "申报容量 / MW", cell: info => <CellEditor value={info.getValue()} kind="number"
        title={info.row.original.unit_id + " 申报容量"}
        onCommit={v => update(info.row.original.unit_id, "quantity_mw", v)}/>, size: 174,
    }),
    columnHelper.accessor("bid_price", {
      header: "当前报价", cell: info => <CellEditor value={info.getValue()} kind="number"
        title={info.row.original.unit_id + " 当前报价"}
        onCommit={v => update(info.row.original.unit_id, "bid_price", v)}/>, size: 150,
    }),
    columnHelper.accessor("marginal_cost", {
      header: "边际成本", cell: info => <CellEditor value={info.getValue()} kind="number"
        title={info.row.original.unit_id + " 边际成本"}
        onCommit={v => update(info.row.original.unit_id, "marginal_cost", v)}/>, size: 150,
    }),
    columnHelper.display({
      id: "remove",
      header: "",
      cell: info => <button className="row-action" title={"删除 " + info.row.original.unit_id}
        aria-label={"删除 " + info.row.original.unit_id} type="button"
        onClick={() => remove(info.row.original.unit_id)}><Trash2 size={15}/></button>,
      size: 38,
    }),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [offers, targetId, onTarget, onChange]);
  const visible = useMemo(() => offers.filter(o => o.unit_id.toLowerCase().includes(search.toLowerCase())), [offers, search]);
  const table = useReactTable({
    data: visible, columns, state: { sorting }, onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(),
  });
  const capacity = offers.reduce((sum, offer) => sum + offer.quantity_mw, 0);
  const addUnit = () => {
    let i = offers.length + 1;
    while (offers.some(o => o.unit_id === "G" + i)) i += 1;
    onChange([...offers, { unit_id: "G" + i, quantity_mw: 100, bid_price: 200, marginal_cost: 180 }]);
    setWarning("");
  };
  return <section className={"data-panel " + (expanded ? "expanded" : "")}>
    <div className="panel-head">
      <div><div className="panel-kicker">GENERATION PORTFOLIO</div><h2>机组申报数据</h2>
        <p>直接编辑容量、报价与边际成本，点选左侧圆点切换目标机组。</p></div>
      <span className="panel-counter">{offers.length} 台机组</span>
    </div>
    <div className="table-toolbar">
      <label className="table-search"><Search size={15}/><input placeholder="搜索机组..." value={search}
        onChange={e => setSearch(e.target.value)} aria-label="搜索机组" /></label>
      <div className="table-tools">
        <button className="subtle-button" type="button" onClick={() => csvExport(
          "powerbid_units.csv",
          ["机组", "申报容量MW", "报价", "边际成本"],
          offers.map(o => [o.unit_id, o.quantity_mw, o.bid_price, o.marginal_cost])
        )}><Download size={15}/><span>导出</span></button>
        <button className="secondary-button" type="button" onClick={addUnit}><Plus size={15}/> 添加机组</button>
      </div>
    </div>
    {warning && <p className="table-warning"><AlertCircle size={14}/>{warning}</p>}
    <div className="table-scroll">
      <table className="units-table">
        <thead>{table.getHeaderGroups().map(group => <tr key={group.id}>{group.headers.map(h => <th key={h.id} style={{ width: h.getSize() }}>
          {h.isPlaceholder ? null : h.column.getCanSort() ? <button type="button" className="sort-button"
            onClick={h.column.getToggleSortingHandler()}>
            {flexRender(h.column.columnDef.header, h.getContext())}
            {h.column.getIsSorted() === "asc" ? <ArrowUp size={12}/> : h.column.getIsSorted() === "desc" ? <ArrowDown size={12}/> : <ArrowUpDown size={12} className="sort-idle"/>}
          </button> : flexRender(h.column.columnDef.header, h.getContext())}</th>)}</tr>)}</thead>
        <tbody>
          {table.getRowModel().rows.map(row => <tr key={row.original.unit_id}
            className={row.original.unit_id === targetId ? "target-row" : ""}
          >{row.getVisibleCells().map(cell => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}
          {table.getRowModel().rows.length === 0 && <tr><td colSpan={columns.length} className="empty-table">没有找到匹配的机组</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="table-foot">
      <span><span className="legend-dot"/> 当前目标 <strong>{targetId}</strong></span>
      <span>总申报容量 <strong>{numeric(capacity)} MW</strong></span>
      <span className="table-foot-note">教学仿真数据 · 单位：价格/MWh</span>
    </div>
  </section>;
}
