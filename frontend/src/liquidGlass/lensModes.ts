/**
 * Framer-inspired visual states, reimplemented for the single PowerBid WebGL
 * lens. No second image, canvas, overlay or competing pixel sample is created.
 *
 * Chart mode is intentionally readable; aggressive glass only appears over
 * decorative page regions. Native buttons and form controls keep priority.
 */
export type CursorVisualMode = "free" | "chart" | "hero" | "grid";

export const VISUAL_LENS_SIZE = {
  free: {width:80,height:54},
  chart: {width:156,height:156},
  hero: {width:128,height:128},
  grid: {width:164,height:164},
} as const;

const DECORATIVE_OCCLUSION = [
  ".pb-hero-copy", ".pb-hero-hud", ".pb-hero-bottom",
  ".pb-constellation-header", ".pb-constellation-detail", ".pb-constellation-hint",
  ".pb-header", ".pb-feature-bottom",
].join(",");

const INTERACTIVE = "button, a[href], input, textarea, select, [contenteditable='true'], [role='slider'], [data-liquid-snap='false']";
const EXPRESSION_SURFACES = ".ta-stat-icon, .ta-card-icon, .pb-risk-halo";

const CHART_PLOT = [
  ".ta-gauge-wrap", ".ta-bars", ".ta-supply-chart", ".recharts-wrapper",
  ".pmss-chart", ".pb-interactive-chart", ".pb-feature-visual .pb-curve-graphic",
  ".pb-browser-chart-panel .pb-curve-graphic",
].join(",");

/** Fit the optical circle inside the 265px editorial grid without overlaying labels. */
function insideBox(element:Element,x:number,y:number,halfLens=0) {
  const r=element.getBoundingClientRect();
  // Match the existing live Canvas sampler: the *whole* lens, not merely
  // the pointer, must fit within the underlying grid texture.
  return x-halfLens>=r.left && x+halfLens<=r.right &&
    y-halfLens>=r.top && y+halfLens<=r.bottom &&
    r.width>halfLens*2 && r.height>halfLens*2;
}
function rectangleOverlap(a:DOMRect,b:DOMRect,pad=6) {
  return a.left-pad<b.right && a.right+pad>b.left &&
    a.top-pad<b.bottom && a.bottom+pad>b.top;
}

/** Hit-testing is performed in viewport coordinates (never texture coords). */
export function resolveVisualMode(root:HTMLElement,x:number,y:number,inside:boolean):CursorVisualMode {
  if (!inside) return "free";
  const hit=document.elementFromPoint(x,y);
  if (!(hit instanceof Element) || !root.contains(hit)) return "free";
  if (hit.closest(INTERACTIVE)) return "free";
  if (hit.closest(CHART_PLOT)) return "chart";
  // Most work happens inside /app. Decorative KPI/icon surfaces provide an
  // immediately discoverable, compact strong-refraction mode without
  // distorting KPI values, labels, form fields or any actionable controls.
  if (hit.closest(EXPRESSION_SURFACES)) return "hero";
  // The Canvas itself usually has pointer-events:none. Detect its projected
  // display rect instead; reject visible text/HUD overlap before magnifying.
  const grid=root.querySelector<HTMLCanvasElement>(".pb-landing .pb-field-canvas");
  if (grid && insideBox(grid,x,y,VISUAL_LENS_SIZE.grid.width/2) && !hit.closest(DECORATIVE_OCCLUSION)) {
    const half=VISUAL_LENS_SIZE.grid.width/2;
    const centerRect=new DOMRect(x-half,y-half,half*2,half*2);
    const obscured=[...root.querySelectorAll<HTMLElement>(DECORATIVE_OCCLUSION)].some(el=>{
      const style=getComputedStyle(el);
      return style.display!=="none" && style.visibility!=="hidden" &&
        rectangleOverlap(centerRect,el.getBoundingClientRect());
    });
    if (!obscured) return "grid";
  }
  // Restrict pronounced refraction to decorative network/hero backgrounds.
  // It must never obscure bids, axis labels, tooltips or editable content.
  if (hit.closest(".pb-flow-network") ||
      (hit.closest(".pb-hero") && !hit.closest(".pb-hero-copy, .pb-hero-hud, .pb-hero-bottom"))) {
    return "hero";
  }
  return "free";
}

export function lensMotion(mode:CursorVisualMode,wasLarge:boolean) {
  // Fractionally under-damped springs for a single soft overshoot.
  // Shrinking large lenses is deliberately a little quicker than expansion.
  if (mode==="grid") return {stiffness:190,damping:15};
  if (mode==="hero") return {stiffness:225,damping:15};
  if (mode==="chart") return {stiffness:255,damping:14};
  if (wasLarge) return {stiffness:260,damping:25};
  return {stiffness:310,damping:32};
}
