export const FREE_ROI_SIZE = 420;
export const SNAP_ROI_PADDING = 160;
export const BASE_WIDTH = 80;
export const BASE_HEIGHT = 54;
// The existing optical lens becomes a larger, perfectly circular viewport over charts.
export const CHART_LENS_SIZE = 118;
export const CHART_LENS_SELECTOR = ".ta-gauge-wrap, .ta-bars, .ta-supply-chart, .recharts-wrapper, .pmss-chart";
export const FREE_OFFSET_Y = -32;
export const SNAP_DISTANCE = 10;
export const RELEASE_DISTANCE = 15;
export const FREE_ROI_PADDING = 64;
export const ROI_DEADZONE = 35;
export const DYNAMIC_SCENE_CHECK_MS = 85;
// Elements whose CSS transforms/animations can change without DOM text updates.
export const DYNAMIC_SCENE_SELECTOR = ".recharts-tooltip-wrapper, .recharts-tooltip-cursor, .recharts-active-dot, [role='tooltip'], [role='dialog'], [data-state='open'], .ta-search-results";

// One lens per meaningful surface: both Smirel and PowerBid share the
// brand-home-link magnetic target, not independent nested icon/text targets.
export const SNAP_SELECTOR = [
  ".sidebar-collapse", ".nav-entry", ".ta-menu-toggle", ".ta-header-icon",
  ".brand-home-link", ".mobile-brand-home", ".ta-global-search",
  ".app button:not(:disabled):not(.mobile-backdrop):not(.ta-settings-overlay)",
  ".app a[href]",
  ".app input:not([type='range']):not([type='checkbox']):not([type='radio']):not([type='hidden']):not([type='file']):not([type='color']):not([type='password'])",
  ".app textarea", ".app select", ".app [contenteditable='true']",
  "[data-liquid-snap='true']",
].join(",");

// Magnetic translation belongs to small buttons, never to form controls,
// graphics, entire cards or layout containers. Wide controls can still get
// the lens, but stay in place so text layout and hit areas remain stable.
export const MAGNETIC_SELECTOR = [
  ".sidebar-collapse", ".nav-entry", ".ta-menu-toggle", ".ta-header-icon",
  ".app button:not(:disabled):not(.mobile-backdrop):not(.ta-settings-overlay)",
  ".app a[href]:not(.brand-home-link)",
  "[data-magnetic-hover='true']",
].join(",");

export const EDITABLE_SELECTOR = "input, textarea, select, [contenteditable='true']";
export const EXCLUDED_SURFACE_SELECTOR = "[data-liquid-snap='false']";
export const MIN_LENS_WIDTH = 42;
export const MIN_LENS_HEIGHT = 36;

export function isEligibleSurface(element: HTMLElement) {
  if (element.matches(":disabled") || element.closest("[aria-hidden='true']")) return false;
  if (element.closest(EXCLUDED_SURFACE_SELECTOR)) return false;
  // The full search shell owns the lens, not the text input inside it.
  if (element.matches(EDITABLE_SELECTOR) && element.closest(".ta-global-search")) return false;
  if (element.matches("input") && ["button", "submit", "reset", "image", "password"].includes((element as HTMLInputElement).type)) return false;
  if (element.matches("[role='slider']")) return false;
  const style = getComputedStyle(element);
  if (style.pointerEvents === "none" || style.visibility !== "visible" || style.display === "none") return false;
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 &&
    rect.right > 0 && rect.bottom > 0 &&
    rect.left < window.innerWidth && rect.top < window.innerHeight;
}

// Keep Smirel + PowerBid as one optical surface. The brand needs more breathing
// room than an ordinary button so the refractive rim cannot cut through the
// wordmark; no extra mount or second lens is created.
export function getLensBounds(element: HTMLElement, _pointerX: number, _pointerY: number) {
  const rect = element.getBoundingClientRect();
  const brand = element.matches(".brand-home-link, .mobile-brand-home");
  const compact = element.matches(".sidebar-collapse, .ta-menu-toggle, .ta-header-icon, .icon-button");
  const paddingX = brand ? 18 : compact ? 6 : 8;
  const paddingY = brand ? 15 : compact ? 6 : 8;

  // The viewport may crop part of a control near its edges; frame the
  // entire *visible* control rather than moving the center away and
  // leaving its first/last letters outside the lens.
  const left = Math.max(0, rect.left - paddingX);
  const right = Math.min(window.innerWidth, rect.right + paddingX);
  const top = Math.max(0, rect.top - paddingY);
  const bottom = Math.min(window.innerHeight, rect.bottom + paddingY);
  const width = Math.max(1, Math.min(window.innerWidth, Math.max(MIN_LENS_WIDTH, right - left)));
  const height = Math.max(1, Math.min(window.innerHeight, Math.max(brand ? 60 : MIN_LENS_HEIGHT, bottom - top)));
  return {
    width,
    height,
    centerX: Math.max(width / 2, Math.min(window.innerWidth - width / 2, (left + right) / 2)),
    centerY: Math.max(height / 2, Math.min(window.innerHeight - height / 2, (top + bottom) / 2)),
  };
}

export function rectDistance(rect: DOMRect, x: number, y: number) {
  const dx = Math.max(rect.left - x, 0, x - rect.right);
  const dy = Math.max(rect.top - y, 0, y - rect.bottom);
  return Math.hypot(dx, dy);
}

export function intersects(rect: DOMRect, left: number, top: number, width: number, height: number) {
  return rect.right >= left && rect.left <= left + width && rect.bottom >= top && rect.top <= top + height;
}


export function resolveSnapTarget(root:HTMLElement, previous:HTMLElement|null, pointerX:number, pointerY:number, chartLens:boolean) {

      if (chartLens) return null;
      let next: HTMLElement | null = null;
      let bestScore = Number.POSITIVE_INFINITY;
      const topElement = document.elementFromPoint(pointerX, pointerY);
      // A pointer over an editable field can snap the full control.
      // Keep native focus/selection hit testing unchanged.
      if (topElement?.closest("[data-liquid-snap='false']")) {
        return null;
      }
      const coveringControl = topElement?.closest("button, a, input, textarea, select");
      for (const candidate of Array.from(root.querySelectorAll<HTMLElement>(SNAP_SELECTOR))) {
        if (candidate.dataset.powerbidLiquidCursor === "true" || !isEligibleSurface(candidate)) continue;
        const rect = candidate.getBoundingClientRect();
        const distance = rectDistance(rect, pointerX, pointerY);
        if (distance > (candidate === previous ? RELEASE_DISTANCE : SNAP_DISTANCE)) continue;
        // Never snap to controls obscured by a popover/backdrop or another
        // interactive element. This also prevents competing nested anchors.
        if (distance === 0 && topElement && topElement !== candidate && !candidate.contains(topElement)) continue;
        if (coveringControl && coveringControl !== candidate && !candidate.contains(coveringControl)) continue;
        const score = distance * 24 + Math.log2(1 + Math.min(rect.width * rect.height, 120000)) -
          (candidate === previous ? 2.4 : 0);
        if (score < bestScore) {
          bestScore = score;
          next = candidate;
        }
      }
      return next;
}

