// Public pages share exactly the same GPU renderer, ROI sampler and magnetic
// motion engine as the authenticated workbench. Lazy-loaded on those routes.
import { LiquidGlassCursor } from "./LiquidGlassCursor";
import "./liquid-glass-cursor.css";

export default function PublicLiquidGlass() {
  return <LiquidGlassCursor />;
}
