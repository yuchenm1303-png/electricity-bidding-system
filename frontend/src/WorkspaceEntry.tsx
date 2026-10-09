import App from "./App";
import type {AccountUser} from "./AccountGate";
import { LiquidGlassCursor } from "./LiquidGlassCursor";
import "./styles.css";
import "./tailadmin-theme.css";
import "./motion.css";
import "./liquid-glass-cursor.css";
import "./smirel-brand.css";

export default function WorkspaceEntry({account,onLogout,onOpenAdmin}:{account?:AccountUser|null;onLogout?:()=>void;onOpenAdmin?:()=>void}) {
  return <><App account={account} onLogout={onLogout} onOpenAdmin={onOpenAdmin}/><LiquidGlassCursor/></>;
}
