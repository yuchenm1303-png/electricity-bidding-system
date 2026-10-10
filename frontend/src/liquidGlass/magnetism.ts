import { MAGNETIC_SELECTOR,isEligibleSurface } from "./targets";
import { stepSpring,type SpringValue } from "./motion";

export type PointerSnapshot = {x:number;y:number;inside:boolean};

/** Manages the interactive translations independently from lens rendering.
    Dynamic chart points are never magnetic targets. */
export function createMagneticController(
  root:HTMLElement,
  getPointer:()=>PointerSnapshot,
  getActiveTarget:()=>HTMLElement|null,
  invalidate:()=>void,
) {
  type MagneticState = {
      x: SpringValue;
      y: SpringValue;
      appliedX: number;
      appliedY: number;
    };

  const magneticStates = new Map<HTMLElement, MagneticState>();
    let magneticTargets: HTMLElement[] = [];

  const refreshMagneticTargets = () => {
      const next = Array.from(root.querySelectorAll<HTMLElement>(MAGNETIC_SELECTOR))
        .filter(element => isEligibleSurface(element) && element.getBoundingClientRect().width <= 210 &&
          element.getBoundingClientRect().height <= 76);
      const nextSet = new Set(next);
      for (const [element] of magneticStates) {
        if (!nextSet.has(element)) {
          element.style.removeProperty("translate");
          magneticStates.delete(element);
        }
      }
      magneticTargets = next;
      for (const element of magneticTargets) {
        if (!magneticStates.has(element)) {
          magneticStates.set(element, {
            x: { value: 0, velocity: 0, target: 0 },
            y: { value: 0, velocity: 0, target: 0 },
            appliedX: 0,
            appliedY: 0,
          });
        }
      }
    };

  const updateMagneticTargets = (dt: number) => {
    const { x:pointerX, y:pointerY, inside:pointerInside } = getPointer();
    const activeTarget = getActiveTarget();
      let settled = true;
      for (const element of magneticTargets) {
        const state = magneticStates.get(element);
        if (!state || !element.isConnected) continue;

        const rect = element.getBoundingClientRect();
        // Pointer hit testing uses the actual, transformed visual bounds.
        // The untransformed center is retained below only to calculate a
        // stable magnetic spring target (avoids translation feedback).
        const baseLeft = rect.left - state.appliedX;
        const baseTop = rect.top - state.appliedY;
        const hoverArea = element.matches(".nav-entry") ? 9 : 11;
        const inside =
          pointerInside &&
          pointerX >= rect.left - hoverArea &&
          pointerX <= rect.right + hoverArea &&
          pointerY >= rect.top - hoverArea &&
          pointerY <= rect.bottom + hoverArea;

        if (inside) {
          const centerX = baseLeft + rect.width / 2;
          const centerY = baseTop + rect.height / 2;
          const normalizedX = Math.max(-1, Math.min(1, (pointerX - centerX) / Math.max(rect.width / 2, 1)));
          const normalizedY = Math.max(-1, Math.min(1, (pointerY - centerY) / Math.max(rect.height / 2, 1)));
          const distance = activeTarget === element ? 4.5 : 5.5;
          state.x.target = normalizedX * distance;
          state.y.target = normalizedY * distance;
        } else {
          state.x.target = 0;
          state.y.target = 0;
        }

        // Slightly under-damped on purpose: the target follows the pointer and
        // gives one restrained elastic swing when it is released.
        stepSpring(state.x, dt, 250, 21);
        stepSpring(state.y, dt, 250, 21);

        const nextX = Math.round(state.x.value * 2) / 2;
        const nextY = Math.round(state.y.value * 2) / 2;
        if (Math.abs(nextX - state.appliedX) >= 0.49 || Math.abs(nextY - state.appliedY) >= 0.49) {
          state.appliedX = nextX;
          state.appliedY = nextY;
          if (Math.abs(nextX) < 0.125 && Math.abs(nextY) < 0.125 && state.x.target === 0 && state.y.target === 0) {
            element.style.removeProperty("translate");
            state.appliedX = 0;
            state.appliedY = 0;
          } else {
            element.style.setProperty("translate", `${nextX}px ${nextY}px`);
          }
          invalidate();
        }

        if (
          Math.abs(state.x.target - state.x.value) >= 0.08 ||
          Math.abs(state.y.target - state.y.value) >= 0.08 ||
          Math.abs(state.x.velocity) >= 0.08 ||
          Math.abs(state.y.velocity) >= 0.08
        ) {
          settled = false;
        }
      }
      return settled;
    };

    refreshMagneticTargets();
    const dispose = () => {
      for (const element of magneticTargets) element.style.removeProperty("translate");
      magneticStates.clear();
    };
    return {refresh:refreshMagneticTargets,update:updateMagneticTargets,dispose};

}

/** Only refresh the magnetic-target registry when a mutation actually changes
 * a control. SVG/Recharts node churn is a raster update, not a target rebuild. */
export function affectsMagneticTargets(record: MutationRecord) {
  if (record.type === "characterData") return false;
  const relevant = (node:Node) => node instanceof Element &&
    (node.matches(MAGNETIC_SELECTOR) || Boolean(node.querySelector(MAGNETIC_SELECTOR)));
  if (record.type === "childList") {
    return [...record.addedNodes,...record.removedNodes].some(relevant);
  }
  if (record.type === "attributes") {
    if (!["class","type","disabled","aria-hidden","data-liquid-snap"].includes(record.attributeName || "")) return false;
    return relevant(record.target);
  }
  return false;
}
