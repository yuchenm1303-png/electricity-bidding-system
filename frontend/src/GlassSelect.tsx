import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search } from "lucide-react";
import "./glass-select.css";

export type GlassSelectOption = { value: string; label: string; disabled?: boolean };

type Props = {
  value: string | number;
  options: GlassSelectOption[];
  onValueChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel: string;
  placeholder?: string;
  className?: string;
  searchable?: boolean;
};

const fold = (text: string) => text.toLocaleLowerCase().trim();

export function GlassSelect({
  value, options, onValueChange, disabled = false, ariaLabel,
  placeholder = "请选择", className = "", searchable, 
}: Props) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [placement, setPlacement] = useState({ top: 0, left: 0, width: 200, height: 280 });
  const id = useId().replace(/:/g, "");
  const chosen = options.find(option => option.value === String(value));
  const searchEnabled = searchable ?? options.length >= 9;
  const filtered = useMemo(
    () => options.filter(option => !query || fold(option.label).includes(fold(query)) || fold(option.value).includes(fold(query))),
    [options, query],
  );
  const selectedInList = filtered.findIndex(option => option.value === String(value));
  const activeOption = filtered[active];

  const measure = () => {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (!rect) return;
    const screenMargin = 10, gap = 7;
    const maxHeight = Math.max(125, Math.min(342, window.innerHeight - 2 * screenMargin));
    const height = Math.min(maxHeight, 18 + filtered.length * 38 + (searchEnabled ? 53 : 0));
    const availableBelow = window.innerHeight - rect.bottom - gap - screenMargin;
    const availableAbove = rect.top - gap - screenMargin;
    const above = availableBelow < Math.min(height, 170) && availableAbove > availableBelow;
    const available = Math.max(100, above ? availableAbove : availableBelow);
    const dropdownHeight = Math.min(height, available);
    const width = Math.min(Math.max(rect.width, Math.min(340, window.innerWidth - 20)), window.innerWidth - 2 * screenMargin);
    const left = Math.min(Math.max(screenMargin, rect.left), window.innerWidth - screenMargin - width);
    const top = above
      ? Math.max(screenMargin, rect.top - gap - dropdownHeight)
      : Math.min(window.innerHeight - screenMargin - dropdownHeight, rect.bottom + gap);
    setPlacement({ top, left, width, height: dropdownHeight });
  };

  useLayoutEffect(() => {
    if (!open) return;
    measure();
    const closeOutside = (event: PointerEvent) => {
      const el = event.target as Node | null;
      if (el && !anchorRef.current?.contains(el) && !menuRef.current?.contains(el)) setOpen(false);
    };
    const handleResize = () => measure();
    const handleScroll = (event: Event) => {
      if (menuRef.current?.contains(event.target as Node)) return;
      measure();
    };
    document.addEventListener("pointerdown", closeOutside, true);
    window.addEventListener("resize", handleResize);
    document.addEventListener("scroll", handleScroll, true);
    return () => {
      document.removeEventListener("pointerdown", closeOutside, true);
      window.removeEventListener("resize", handleResize);
      document.removeEventListener("scroll", handleScroll, true);
    };
  }, [open, filtered.length, searchEnabled]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!open) return;
    const index = selectedInList >= 0 ? selectedInList : filtered.findIndex(option => !option.disabled);
    setActive(Math.max(0, index));
    if (searchEnabled) requestAnimationFrame(() => searchRef.current?.focus());
  }, [open]);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>(`[data-option-index="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active, open, filtered.length]);

  const choose = (option: GlassSelectOption) => {
    if (option.disabled) return;
    onValueChange(option.value);
    setOpen(false);
    setQuery("");
    requestAnimationFrame(() => anchorRef.current?.focus());
  };
  const move = (increment: number) => {
    if (!filtered.length) return;
    for (let delta = 1; delta <= filtered.length; delta++) {
      const i = (active + increment * delta + filtered.length * 2) % filtered.length;
      if (!filtered[i].disabled) { setActive(i); break; }
    }
  };
  const keydown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      if (open) { event.preventDefault(); event.stopPropagation(); setOpen(false); setQuery(""); anchorRef.current?.focus(); }
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) { setOpen(true); setQuery(""); }
      else move(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Home" && open) {
      event.preventDefault(); setActive(Math.max(0, filtered.findIndex(option => !option.disabled)));
    } else if (event.key === "End" && open) {
      event.preventDefault(); setActive(Math.max(0, [...filtered].map((option,index)=>option.disabled ? -1 : index).reduce((max,index)=>Math.max(max,index),-1)));
    } else if (event.key === "Enter" || (event.key === " " && event.target !== searchRef.current)) {
      event.preventDefault();
      if (!open) { setOpen(true); setQuery(""); }
      else if (activeOption) choose(activeOption);
    } else if (event.key === "Tab" && open) {
      setOpen(false); setQuery("");
    }
  };

  const portalTarget = document.querySelector<HTMLElement>(".app") ?? document.body;
  return <>
    <button ref={anchorRef} type="button" disabled={disabled}
      className={["glass-select-trigger", className].filter(Boolean).join(" ")}
      aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open}
      aria-controls={open ? id + "-list" : undefined}
      data-open={open ? "true" : undefined}
      onClick={() => { if (!disabled) { setOpen(!open); setQuery(""); } }}
      onKeyDown={keydown}
    >
      <span className="glass-select-value" title={chosen?.label || placeholder}>{chosen?.label || placeholder}</span>
      <ChevronDown size={15} className="glass-select-chevron" aria-hidden="true" />
    </button>
    {open && createPortal(<div ref={menuRef} className="glass-select-popover"
        data-glass-dropdown="true" role="presentation"
        style={{ top: placement.top, left: placement.left, width: placement.width, maxHeight: placement.height }}
        onKeyDown={keydown}>
      {searchEnabled && <div className="glass-select-search">
        <Search size={15} aria-hidden="true" />
        <input ref={searchRef} value={query} onChange={event => { setQuery(event.target.value); setActive(0); }}
          aria-label={"搜索" + ariaLabel} placeholder="搜索名称或编号..." />
      </div>}
      <div id={id + "-list"} role="listbox" aria-label={ariaLabel}
        aria-activedescendant={activeOption ? id + "-option-" + active : undefined}
        className="glass-select-options">
        {filtered.map((option, index) => <div key={option.value} role="option"
          id={id + "-option-" + index}
          aria-selected={option.value === String(value)}
          aria-disabled={option.disabled || undefined}
          data-option-index={index}
          data-active={active === index ? "true" : undefined}
          className="glass-select-option"
          onPointerMove={() => setActive(index)}
          onClick={() => choose(option)}
          title={option.label}>
          <span>{option.label}</span>
          {option.value === String(value) && <Check size={15} aria-hidden="true"/>}
        </div>)}
        {!filtered.length && <div className="glass-select-empty">没有匹配的选项</div>}
      </div>
    </div>, portalTarget)}
  </>;
}
