import { useEffect, useRef, useState } from "react";
import {
  BASE_WIDTH, BASE_HEIGHT,
  DYNAMIC_SCENE_CHECK_MS, DYNAMIC_SCENE_SELECTOR,
  FREE_ROI_SIZE, FREE_OFFSET_Y,
  getLensBounds, intersects, resolveSnapTarget
} from "./liquidGlass/targets";
import { stepSpring, springSettled, type SpringValue } from "./liquidGlass/motion";
import { opticalProfile, opticalRadius, type LensMode } from "./liquidGlass/optics";
import { resolveVisualMode, VISUAL_LENS_SIZE, lensMotion, type CursorVisualMode } from "./liquidGlass/lensModes";
import { createMagneticController, affectsMagneticTargets } from "./liquidGlass/magnetism";
import { rasterizePortal, composeLiveGrid } from "./liquidGlass/sceneRaster";
import { createGlassRenderer } from "./liquidGlass/renderer";
import { createRoiManager } from "./liquidGlass/roi";

export function LiquidGlassCursor() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);
  // Retained across context recreation; a stationary pointer must not lose
  // the optical lens until the user moves again.
  const pointerRef = useRef({x:0,y:0,inside:false,known:false});
  const [contextVersion, setContextVersion] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const dot = dotRef.current;
    const root = canvas?.closest("#root") as HTMLElement | null;
    if (!canvas || !dot || !root) return;

    const finePointer = window.matchMedia("(pointer: fine)").matches;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!finePointer || reducedMotion) return;

    const renderer = createGlassRenderer(canvas);
    if (!renderer) return;
    const capture = document.createElement("canvas");
    const scratch = document.createElement("canvas");
    const gridBackdrop = document.createElement("canvas");
    const tooltipBackdrop = document.createElement("canvas");
    const dpr = Math.min(
      Math.max(1, Math.min(window.devicePixelRatio || 1, 1.75)),
      renderer.maxTextureSize / Math.max(window.innerWidth, window.innerHeight, 1),
    );
    const resizeSurfaces = (cssWidth: number, cssHeight: number) => {
      const nextWidth = Math.max(1, Math.round(cssWidth * dpr));
      const nextHeight = Math.max(1, Math.round(cssHeight * dpr));
      if (canvas.width === nextWidth && canvas.height === nextHeight) return false;
      for (const target of [canvas, capture, scratch, gridBackdrop, tooltipBackdrop]) {
        target.width = nextWidth; target.height = nextHeight;
      }
      canvas.style.width = String(cssWidth)+"px";
      canvas.style.height = String(cssHeight)+"px";
      renderer.resetTexture();
      return true;
    };
    resizeSurfaces(FREE_ROI_SIZE, FREE_ROI_SIZE);

    let pointerX = pointerRef.current.known ? pointerRef.current.x : window.innerWidth / 2;
    let pointerY = pointerRef.current.known ? pointerRef.current.y : window.innerHeight / 2;
    let pointerInside = pointerRef.current.inside;
    let pressed = false;
    const pressure: SpringValue = { value: 0, velocity: 0, target: 0 };
    let activeTarget: HTMLElement | null = null;
    let visualMode:CursorVisualMode = "free";
    let chartLens = false;
    let raf = 0;
    let lastTime = performance.now();
    let lastCapture = 0;
    let lastRoiLeft = Number.NaN;
    let lastRoiTop = Number.NaN;
    let rasterDirty = true;
    let gridBackdropReady = false;
    let tooltipBackdropReady = false;
    let tooltipBackdropLeft = Number.NaN;
    let tooltipBackdropTop = Number.NaN;
    let lastTooltipBaseCapture = 0;
    let tooltipAnimationUntil = 0;
    let gridBackdropLeft = Number.NaN;
    let gridBackdropTop = Number.NaN;
    let staticDirty = true;
    let textureReady = false;
    let snapDirty = true;
    let running = false;
    let sceneTimer = 0;
    let lastSceneSignature = "";
    let animationWatchUntil = 0;
    let urgentCapture = true;
    const roi = createRoiManager(
      resizeSurfaces,
      () => {rasterDirty=true;},
      () => {textureReady=false;lastRoiLeft=Number.NaN;lastRoiTop=Number.NaN;gridBackdropReady=false;tooltipBackdropReady=false;},
    );

    const x: SpringValue = { value: pointerX, velocity: 0, target: pointerX };
    const y: SpringValue = { value: pointerY + FREE_OFFSET_Y, velocity: 0, target: pointerY + FREE_OFFSET_Y };
    const width: SpringValue = { value: BASE_WIDTH, velocity: 0, target: BASE_WIDTH };
    const height: SpringValue = { value: BASE_HEIGHT, velocity: 0, target: BASE_HEIGHT };
    const snap: SpringValue = { value: 0, velocity: 0, target: 0 };
    const cornerRadius: SpringValue = { value: BASE_HEIGHT/2, velocity:0, target:BASE_HEIGHT/2 };
    const initialOptics = opticalProfile("free",0,0,0);
    const optical = {
      strength:{value:initialOptics.strength,velocity:0,target:initialOptics.strength},
      pinch:{value:initialOptics.pinch,velocity:0,target:initialOptics.pinch},
      aberration:{value:initialOptics.aberration,velocity:0,target:initialOptics.aberration},
      zoom:{value:initialOptics.zoom,velocity:0,target:initialOptics.zoom},
      wobble:{value:initialOptics.wobble,velocity:0,target:initialOptics.wobble},
      reflection:{value:initialOptics.reflection,velocity:0,target:initialOptics.reflection},
    } satisfies Record<keyof typeof initialOptics,SpringValue>;

    const magnetism = createMagneticController(
      root,
      () => ({x:pointerX,y:pointerY,inside:pointerInside}),
      () => activeTarget,
      () => {staticDirty=true;rasterDirty=true;snapDirty=true;},
    );

    // The four Framer-inspired visual states share this original WebGL lens.
    // Only the intent and targets change here; geometry/optics are sprung in
    // the same requestAnimationFrame and never use CSS scale overlays.
    const updateLensIntent = () => {
      const next = resolveVisualMode(root,pointerX,pointerY,pointerInside);
      if (next === visualMode) return;
      visualMode = next;
      chartLens = next==="chart" || next==="grid";
      snapDirty = true;
      rasterDirty = true;
      staticDirty = true;
    };

    const updateTargets = () => {
      if (!snapDirty && !activeTarget) return;
      snapDirty = false;
      const previousTarget = activeTarget;
      const target = resolveSnapTarget(root,previousTarget,pointerX,pointerY,chartLens);
      activeTarget = target;
      if (target !== previousTarget) {
        rasterDirty = true;
        roi.clearLock();
        if (target) {
          const { width: finalLensWidth, height: finalLensHeight } = getLensBounds(target, pointerX, pointerY);
          // Full-width controls require a full-width capture. A fixed 1200px
          // cap clipped large buttons even after the lens geometry was fixed.
          roi.setSnapDimensions(finalLensWidth,finalLensHeight);
        }
      }
      if (target) {
        const lens = getLensBounds(target, pointerX, pointerY);
        x.target = lens.centerX;
        y.target = lens.centerY;
        width.target = lens.width;
        height.target = lens.height;
        snap.target = 1;
      } else if (visualMode !== "free") {
        // Circle modes follow the cursor directly; the ROI and shader center
        // both use the exact same viewport CSS-pixel coordinate system.
        const geometry = VISUAL_LENS_SIZE[visualMode];
        x.target = Math.max(geometry.width / 2 + 4, Math.min(window.innerWidth - geometry.width / 2 - 4, pointerX));
        y.target = Math.max(geometry.height / 2 + 4, Math.min(window.innerHeight - geometry.height / 2 - 4, pointerY));
        width.target = geometry.width;
        height.target = geometry.height;
        snap.target = 0;
      } else {
        // Keep the unsnapped lens wholly on-screen near the top/bottom.
        x.target = Math.max(BASE_WIDTH / 2 + 6, Math.min(window.innerWidth - BASE_WIDTH / 2 - 6, pointerX));
        y.target = Math.max(BASE_HEIGHT / 2 + 6, Math.min(window.innerHeight - BASE_HEIGHT / 2 - 6, pointerY + FREE_OFFSET_Y));
        width.target = BASE_WIDTH;
        height.target = BASE_HEIGHT;
        snap.target = 0;
      }
    };

    // Fast composition is safe only over unobstructed topology pixels.
    // Cards, labels and explanatory text must retain native paint order.
    // Fall back to the original full DOM raster whenever the glass overlaps
    // those layers; other areas retain the static backdrop + live Canvas path.
    const liveGridForLens = () => {
      if (!chartLens || !pointerInside || document.hidden) return null;
      const grid = root.querySelector<HTMLCanvasElement>(".pb-landing .pb-field-canvas");
      if (!grid) return null;
      const st = getComputedStyle(grid);
      if (st.visibility !== "visible" || st.display === "none") return null;
      const bounds = grid.getBoundingClientRect();
      const halfWidth = width.value / 2, halfHeight = height.value / 2;
      if (x.value-halfWidth < bounds.left || x.value+halfWidth > bounds.right ||
          y.value-halfHeight < bounds.top || y.value+halfHeight > bounds.bottom) return null;
      const lens = {left:x.value-halfWidth,top:y.value-halfHeight,
        right:x.value+halfWidth,bottom:y.value+halfHeight};
      for (const overlay of root.querySelectorAll<HTMLElement>(
        ".pb-hero-hud, .pb-constellation-header, .pb-constellation-detail, .pb-constellation-hint, .pb-hero-copy")) {
        const style = getComputedStyle(overlay);
        if (style.display === "none" || style.visibility === "hidden") continue;
        const r=overlay.getBoundingClientRect();
        if (r.left < lens.right && r.right > lens.left &&
            r.top < lens.bottom && r.bottom > lens.top) return null;
      }
      return grid;
    };

    const liveChartTooltip = () => {
      if (!chartLens || !pointerInside || document.hidden) return null;
      // A dashboard can have several Recharts charts, each with its own
      // tooltip wrapper. Pick the currently visible one, not the first DOM
      // match (which may belong to a non-hovered chart).
      for (const tip of root.querySelectorAll<HTMLElement>(".recharts-tooltip-wrapper")) {
        const st=getComputedStyle(tip);
        if (st.display === "none" || st.visibility === "hidden" ||
            Number(st.opacity) < 0.002) continue;
        if (!intersects(tip.getBoundingClientRect(),roi.state.left,roi.state.top,
            roi.state.width,roi.state.height)) continue;
        return tip;
      }
      return null;
    };

    const uploadTexture = (roiLeft: number, roiTop: number, now: number) => {
      const moved = Math.abs(roiLeft - lastRoiLeft) >= 0.75 || Math.abs(roiTop - lastRoiTop) >= 0.75;
      if (!rasterDirty && !moved) return;
      // The ROI and the uploaded pixels are an atomic pair: never apply a new
      // coordinate origin to an old texture. Moving to a new ROI bypasses the
      // ordinary 32ms stationary-cache throttle.
      const grid = liveGridForLens();
      const tip = !grid ? liveChartTooltip() : null;
      // The tip is cheap to render separately; its static chart backdrop
      // stays cached while the hover position or value changes.
      const minCaptureInterval = tip ? 30 : grid ? 24 : activeTarget ? 16 : 32;
      if (!moved && !urgentCapture && now - lastCapture < minCaptureInterval) return;
      lastCapture = now;
      if (grid) {
        if (!gridBackdropReady || staticDirty ||
            gridBackdropLeft !== roiLeft || gridBackdropTop !== roiTop) {
          if (!rasterizePortal(root,gridBackdrop,scratch,null,roiLeft,roiTop,
              roi.state.width,roi.state.height,dpr,true)) {
            textureReady=false;return;
          }
          gridBackdropReady=true;
          gridBackdropLeft=roiLeft;gridBackdropTop=roiTop;
          staticDirty=false;
        }
        if (!composeLiveGrid(gridBackdrop,capture,grid,roiLeft,roiTop,
            roi.state.width,roi.state.height,dpr)) {
          textureReady=false;return;
        }
      } else if (tip) {
        if (!tooltipBackdropReady || staticDirty ||
            tooltipBackdropLeft !== roiLeft || tooltipBackdropTop !== roiTop ||
            now-lastTooltipBaseCapture > 180) {
          if (!rasterizePortal(root,tooltipBackdrop,scratch,null,roiLeft,roiTop,
              roi.state.width,roi.state.height,dpr,false,"background")) {
            textureReady=false;return;
          }
          tooltipBackdropReady=true;
          tooltipBackdropLeft=roiLeft;tooltipBackdropTop=roiTop;
          lastTooltipBaseCapture=now;
          staticDirty=false;
        }
        const ctx=capture.getContext("2d");
        if (!ctx) {textureReady=false;return;}
        ctx.setTransform(1,0,0,1,0,0);
        ctx.globalAlpha=1;
        ctx.clearRect(0,0,capture.width,capture.height);
        ctx.drawImage(tooltipBackdrop,0,0);
        if (!rasterizePortal(root,capture,scratch,null,roiLeft,roiTop,
            roi.state.width,roi.state.height,dpr,false,"overlay")) {
          textureReady=false;return;
        }
      } else if (!rasterizePortal(root,capture,scratch,null,roiLeft,roiTop,
          roi.state.width,roi.state.height,dpr)) {
        textureReady=false;return;
      }
      if (renderer.upload(capture)) {
        // The sampled ROI always belongs to the pixels actually uploaded.
        lastRoiLeft = roiLeft;lastRoiTop = roiTop;
        textureReady = true;rasterDirty = false;
        urgentCapture = false;
      } else {
        textureReady = false;rasterDirty = true;
      }
    };

    const ensureFrame = () => {
      if (running) return;
      running = true;
      lastTime = performance.now();
      raf = window.requestAnimationFrame(frame);
    };

    const frame = (now: number) => {
      const dt = Math.min(0.064, Math.max(0.001, (now - lastTime) / 1000));
      lastTime = now;
      const magneticSettled = magnetism.update(dt);
      updateLensIntent();
      updateTargets();

      const snapping = Boolean(activeTarget) || snap.target > 0.001;
      stepSpring(x, dt, snapping ? 300 : 500, snapping ? 25 : 60);
      stepSpring(y, dt, snapping ? 300 : 500, snapping ? 25 : 60);
      const geometrySpring = snapping
        ? {stiffness:235,damping:19}
        : lensMotion(visualMode,width.value>140);
      stepSpring(width,dt,geometrySpring.stiffness,geometrySpring.damping);
      stepSpring(height,dt,geometrySpring.stiffness,geometrySpring.damping);
      stepSpring(snap, dt, 220, 18);
      // Firm compression on contact, then one softer elastic release.
      stepSpring(pressure, dt, pressed ? 620 : 400, pressed ? 38 : 23);
      const deformation = Math.max(-0.22, Math.min(1.08, pressure.value));
      const pressWeight = Math.max(0,Math.min(1,deformation));
      const releaseWeight = Math.max(0,-deformation);
      const mode:LensMode = activeTarget?.matches(".brand-home-link, .mobile-brand-home, .pb-logo-link, .pb-identity-brand") ? "brand"
        : activeTarget?.matches(".ta-global-search, .pb-identity-input-wrap, input, textarea, select, [contenteditable='true']") ? "reading"
        : activeTarget ? "control" : visualMode;
      // Readable profile names make QA possible without another DOM overlay.
      canvas.dataset.glassMode = mode;
      // Shape, position and optics all spring towards the *same* target mode.
      // A fast target-to-target move thus continues from its visible state
      // rather than abruptly switching the refraction before the lens arrives.
      cornerRadius.target = opticalRadius(mode,width.target,height.target,activeTarget);
      stepSpring(cornerRadius,dt,310,35);
      const desiredOptics = opticalProfile(mode,snap.value,pressWeight,releaseWeight);
      for(const name of Object.keys(optical) as Array<keyof typeof optical>) {
        optical[name].target = desiredOptics[name];
        stepSpring(optical[name],dt,320,38);
      }

      roi.update(x.value,y.value,width.value,height.value,activeTarget,snap.value);
      uploadTexture(roi.state.left, roi.state.top, now);

      const hasSample = textureReady && Number.isFinite(lastRoiLeft) && Number.isFinite(lastRoiTop);
      canvas.style.transform = `translate3d(${lastRoiLeft}px, ${lastRoiTop}px, 0)`;
      dot.style.transform = `translate3d(${pointerX - 1.75}px, ${pointerY - 1.75}px, 0)`;
      canvas.style.opacity = pointerInside && hasSample ? "1" : "0";
      dot.style.opacity = pointerInside ? (snap.value > 0.4 ? ".42" : ".86") : "0";

      if (hasSample) {
        renderer.render({
          canvasWidth:canvas.width,canvasHeight:canvas.height,
          x:x.value,y:y.value,
          width:width.value * (1 + 0.065 * deformation),
          height:height.value * (1 - 0.155 * deformation),
          roiLeft:lastRoiLeft,roiTop:lastRoiTop,dpr,
          strength:optical.strength.value,pinch:optical.pinch.value,
          aberration:optical.aberration.value,zoom:optical.zoom.value,
          wobble:optical.wobble.value,reflection:optical.reflection.value,
          cornerRadius:Math.max(2,cornerRadius.value),
          time:now/1000,
        });
      }

      const settled =
        Math.abs(x.target - x.value) < 0.08 &&
        Math.abs(y.target - y.value) < 0.08 &&
        Math.abs(width.target - width.value) < 0.08 &&
        Math.abs(height.target - height.value) < 0.08 &&
        Math.abs(snap.target - snap.value) < 0.002 &&
        Math.abs(x.velocity) < 0.08 &&
        Math.abs(y.velocity) < 0.08 &&
        Math.abs(width.velocity) < 0.08 &&
        Math.abs(height.velocity) < 0.08 &&
        Math.abs(pressure.target - pressure.value) < 0.001 &&
        Math.abs(pressure.velocity) < 0.01 &&
        springSettled(cornerRadius,0.02,0.09) &&
        Object.values(optical).every(state=>springSettled(state,0.0003,0.007)) &&
        magneticSettled;

      // Pointer/input/layout events wake the loop. A stationary cursor does
      // not need continuous DOM measurements and WebGL draws once springs settle.
      if (tooltipAnimationUntil > now && liveChartTooltip()) rasterDirty=true;
      if (settled && !rasterDirty && !snapDirty) {
        running = false;
        return;
      }
      raf = window.requestAnimationFrame(frame);
    };

    // Tooltip movement is often a compositor-only CSS transform. Track the
    // actual on-screen rectangles as well as DOM mutations. The timer checks
    // at ~12Hz but uploads a new texture only when the scene has changed.
    const dynamicSignature = () => {
      if (!pointerInside || !Number.isFinite(roi.state.left) || !Number.isFinite(roi.state.top)) return "";
      const parts: string[] = [];
      for (const node of root.querySelectorAll<Element>(DYNAMIC_SCENE_SELECTOR)) {
        if (node.closest("[data-powerbid-liquid-cursor='true']") ||
            node.matches(".recharts-tooltip-wrapper")) continue;
        const st = getComputedStyle(node);
        if (st.display === "none" || st.visibility === "hidden" || Number(st.opacity) < 0.01) continue;
        const r = node.getBoundingClientRect();
        if (!intersects(r, roi.state.left, roi.state.top, roi.state.width, roi.state.height)) continue;
        parts.push([node.tagName, node.getAttribute("class") || "",
          Math.round(r.left * 4), Math.round(r.top * 4),
          Math.round(r.width * 4), Math.round(r.height * 4),
          st.opacity, st.fill, st.stroke, st.backgroundColor, st.color,
          (node.textContent || "").slice(0, 72)].join("|"));
      }
      return parts.join("\\n");
    };
    const checkDynamicScene = () => {
      sceneTimer = 0;
      if (!pointerInside) return;
      const now = performance.now();
      const signature = dynamicSignature();
      const animating = now < animationWatchUntil;
      // Native topology draws now emit powerbid:grid-frame directly; keep
      // the normal 85ms observer for ordinary animated DOM and tooltips.
      if (signature !== lastSceneSignature || (animating && now-lastCapture >= DYNAMIC_SCENE_CHECK_MS)) {
        lastSceneSignature = signature;
        staticDirty = true;
        rasterDirty = true;
        ensureFrame();
      }
      if (signature || animating) sceneTimer = window.setTimeout(checkDynamicScene,DYNAMIC_SCENE_CHECK_MS);
    };
    const watchScene = () => {
      if (pointerInside && !sceneTimer) sceneTimer = window.setTimeout(checkDynamicScene, DYNAMIC_SCENE_CHECK_MS);
    };
    const onSceneAnimation = (event: Event) => {
      if (!(event.target instanceof Element) ||
          event.target.closest("[data-powerbid-liquid-cursor='true']")) return;
      if (event.target.closest(".recharts-tooltip-wrapper")) {
        tooltipAnimationUntil=performance.now()+500;
        rasterDirty=true;ensureFrame();return;
      }
      const bounds = event.target.getBoundingClientRect();
      // Decorative animations elsewhere in the dashboard must not trigger
      // endless ROI redraws. Include a generous outer margin so transitions
      // entering the sampled region are still observed.
      const margin = 120;
      if (Number.isFinite(roi.state.left) && Number.isFinite(roi.state.top) &&
          !intersects(bounds, roi.state.left - margin, roi.state.top - margin,
            roi.state.width + margin * 2, roi.state.height + margin * 2)) return;
      animationWatchUntil = Math.max(animationWatchUntil, performance.now() + 1400);
      staticDirty = true;
      rasterDirty = true;
      ensureFrame();
      watchScene();
    };
    const sceneAnimationEvents = [
      "transitionrun", "transitionend", "transitioncancel",
      "animationstart", "animationiteration", "animationend", "animationcancel",
    ];

    // Browsers can evict a GPU context after sleep or tab suspension. Avoid
    // displaying stale pixels, and recreate shaders/textures on restoration.
    const onContextLost = (event:Event) => {
      event.preventDefault();
      textureReady=false;
      canvas.style.opacity="0";
      running=false;
      window.cancelAnimationFrame(raf);
    };
    const onContextRestored = () => setContextVersion(version=>version+1);
    canvas.addEventListener("webglcontextlost",onContextLost);
    canvas.addEventListener("webglcontextrestored",onContextRestored);

    const wake = () => ensureFrame();
    const handlePointerMove = (event: PointerEvent) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      pointerInside = true;
      pointerRef.current={x:pointerX,y:pointerY,inside:true,known:true};
      snapDirty = true;
      // Static page pixels do not change when the pointer merely moves.
      // Chart tooltips are compositor-driven and still need rapid repaint.
      if (chartLens || event.target instanceof Element &&
          Boolean(event.target.closest(".recharts-wrapper, .ta-supply-chart, .ta-bars, .ta-gauge-wrap, .pmss-chart, .pb-field-canvas"))) {
        rasterDirty = true;
        if (chartLens) tooltipAnimationUntil=performance.now()+500;
      }
      wake();
      watchScene();
    };
    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      pressed = true;
      pressure.target = 1;
      // A brief tap still has a visible contact phase before its release.
      pressure.velocity = Math.max(pressure.velocity, 5);
      rasterDirty = true;
      snapDirty = true;
      wake();
    };
    const handlePointerUp = () => {
      if (!pressed) return;
      pressed = false;
      pressure.target = 0;
      pressure.value = Math.max(pressure.value, 0.22);
      pressure.velocity = Math.min(pressure.velocity, -3.5);
      rasterDirty = true;
      snapDirty = true;
      wake();
    };
    const handlePointerLeave = () => {
      pointerInside = false;
      pointerRef.current.inside=false;
      chartLens = false;
      visualMode = "free";
      pressed = false;
      pressure.target = 0;
      activeTarget = null;
      snap.target = 0;
      snapDirty = true;
      lastSceneSignature = "";
      animationWatchUntil = 0;
      tooltipAnimationUntil = 0;
      window.clearTimeout(sceneTimer);
      sceneTimer = 0;
      wake();
    };
    const handlePointerEnter = () => {
      pointerInside = true;
      pointerRef.current.inside=true;
      snapDirty = true; rasterDirty = true; wake(); watchScene();
    };
    const handleScroll = () => {
      roi.clearLock(); staticDirty=true;rasterDirty = true;urgentCapture=true; snapDirty = true; wake(); watchScene();
    };
    // Editing changes input.value without mutating DOM text or attributes.
    const handleInput = () => {staticDirty=true; rasterDirty = true;urgentCapture=true; wake(); };
    const handleResize = () => {
      roi.reset();
      staticDirty=true;
      rasterDirty = true;
      urgentCapture = true;
      snapDirty = true;
      wake();
    };

    const observer = new MutationObserver((records) => {
      const updates = records.filter(record => {
        const el = record.target instanceof Element
          ? record.target : record.target.parentElement;
        return !el?.closest("[data-powerbid-liquid-cursor='true']");
      });
      if (!updates.length) return;
      const tooltipOnly = updates.every(record=>{
        const el=record.target instanceof Element
          ? record.target : record.target.parentElement;
        return Boolean(el?.closest(".recharts-tooltip-wrapper"));
      });
      if (!tooltipOnly && updates.some(affectsMagneticTargets)) {
        magnetism.refresh();
        snapDirty = true;
      }
      if (!tooltipOnly) staticDirty=true;
      else tooltipAnimationUntil=performance.now()+450;
      rasterDirty = true;
      wake();
      watchScene();
    });
    observer.observe(root, {
      childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ["type", "value", "placeholder", "style", "class", "transform",
        "opacity", "fill", "stroke", "d", "x", "y", "cx", "cy", "r",
        "width", "height", "aria-hidden", "data-state", "disabled", "data-liquid-snap"],
    });
    const resizeObserver = new ResizeObserver(() => { staticDirty=true; rasterDirty = true; snapDirty = true; wake(); });
    resizeObserver.observe(root);

    document.fonts?.ready.then(() => { staticDirty=true; rasterDirty = true; wake(); }).catch(() => {});

    const handleGridPaint = (event:Event) => {
      if (!pointerInside || document.hidden ||
          !(event.target instanceof HTMLCanvasElement) ||
          !event.target.matches(".pb-landing .pb-field-canvas")) return;
      if (!Number.isFinite(roi.state.left) || !Number.isFinite(roi.state.top) ||
          !intersects(event.target.getBoundingClientRect(),roi.state.left,
            roi.state.top,roi.state.width,roi.state.height)) return;
      rasterDirty=true;
      ensureFrame();
    };
    root.addEventListener("powerbid:grid-frame",handleGridPaint);
    root.addEventListener("pointermove", handlePointerMove);
    root.addEventListener("pointerdown", handlePointerDown);
    root.addEventListener("pointerup", handlePointerUp);
    root.addEventListener("pointercancel", handlePointerUp);
    root.addEventListener("pointerleave", handlePointerLeave);
    root.addEventListener("pointerenter", handlePointerEnter);
    root.addEventListener("input", handleInput, true);
    root.addEventListener("change", handleInput, true);
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", handleResize);
    window.addEventListener("blur", handlePointerLeave);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
    for (const event of sceneAnimationEvents) root.addEventListener(event, onSceneAnimation, true);
    document.documentElement.classList.add("powerbid-liquid-cursor-active");

    ensureFrame();

    return () => {
      window.cancelAnimationFrame(raf);
      canvas.removeEventListener("webglcontextlost",onContextLost);
      canvas.removeEventListener("webglcontextrestored",onContextRestored);
      window.clearTimeout(sceneTimer);
      observer.disconnect();
      resizeObserver.disconnect();
      root.removeEventListener("powerbid:grid-frame",handleGridPaint);
      root.removeEventListener("pointermove", handlePointerMove);
      root.removeEventListener("pointerdown", handlePointerDown);
      root.removeEventListener("pointerup", handlePointerUp);
      root.removeEventListener("pointercancel", handlePointerUp);
      root.removeEventListener("pointerleave", handlePointerLeave);
      root.removeEventListener("pointerenter", handlePointerEnter);
      root.removeEventListener("input", handleInput, true);
      root.removeEventListener("change", handleInput, true);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("blur", handlePointerLeave);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
      for (const event of sceneAnimationEvents) root.removeEventListener(event, onSceneAnimation, true);
      document.documentElement.classList.remove("powerbid-liquid-cursor-active");
      magnetism.dispose();
      renderer.dispose();
    };
  }, [contextVersion]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className="powerbid-liquid-cursor-canvas"
        data-powerbid-liquid-cursor="true"
        aria-hidden="true"
      />
      <div
        ref={dotRef}
        className="powerbid-liquid-cursor-dot"
        data-powerbid-liquid-cursor="true"
        aria-hidden="true"
      />
    </>
  );
}
