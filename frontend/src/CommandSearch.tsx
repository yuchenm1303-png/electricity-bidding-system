import { useEffect, useRef, useState } from "react";
import { Search, type LucideIcon } from "lucide-react";
import type { WorkspaceView } from "./types";

export type SearchDestination = {
  id: WorkspaceView;
  label: string;
  hint: string;
  icon: LucideIcon;
};

export function CommandSearch({ destinations, onNavigate }: {
  destinations: SearchDestination[];
  onNavigate: (view: WorkspaceView) => void;
}) {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        ref.current?.focus();
      }
      if (event.key === "Escape") {
        ref.current?.blur();
        setFocused(false);
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
  const filtered = destinations.filter(item =>
    item.label.includes(query.trim()) || item.hint.includes(query.trim()) ||
    item.id.includes(query.trim().toLowerCase())
  );
  const navigate = (destination: WorkspaceView) => {
    onNavigate(destination);
    setQuery("");
    setFocused(false);
    ref.current?.blur();
  };
  return <div className="ta-global-search">
    <Search size={19}/>
    <input ref={ref} type="search" aria-label="搜索页面" placeholder="搜索页面或输入命令..."
      value={query} onFocus={() => setFocused(true)}
      onBlur={() => window.setTimeout(() => setFocused(false), 140)}
      onChange={event => setQuery(event.target.value)}
      onKeyDown={event => {
        if (event.key === "Enter" && filtered[0]) navigate(filtered[0].id);
      }}/>
    <kbd>⌘ K</kbd>
    {focused && query.trim() && <div className="ta-search-results">
      {filtered.length ? filtered.map(item => {
        const Icon = item.icon;
        return <button key={item.id} type="button" onMouseDown={event => event.preventDefault()}
          onClick={() => navigate(item.id)}>
          <Icon size={17}/><span>{item.label}</span><small>{item.hint}</small>
        </button>;
      }) : <div className="ta-search-empty">没有找到匹配的页面</div>}
    </div>}
  </div>;
}
