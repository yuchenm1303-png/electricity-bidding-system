import App from "./App";
import type {AccountUser} from "./AccountGate";
import { LiquidGlassCursor } from "./LiquidGlassCursor";
import "./styles.css";
import "./tailadmin-theme.css";
import "./motion.css";
import "./liquid-glass-cursor.css";
import "./smirel-brand.css";
import "./workspace-buttons.css";
import "./icon-interactions.css";
import "./workspace-editorial.css";

export default function WorkspaceEntry({account,onLogout,onOpenAdmin,onOpenProfile}:{account?:AccountUser|null;onLogout?:()=>void;onOpenAdmin?:()=>void;onOpenProfile?:()=>void}) {
  return <><App account={account} onLogout={onLogout} onOpenAdmin={onOpenAdmin} onOpenProfile={onOpenProfile}/><LiquidGlassCursor/></>;
}
