import { useEffect, useRef, useState } from "react";
import {
  BASE_WIDTH, BASE_HEIGHT, CHART_LENS_SIZE, CHART_LENS_SELECTOR,
  DYNAMIC_SCENE_CHECK_MS, DYNAMIC_SCENE_SELECTOR,
  FREE_ROI_SIZE, FREE_OFFSET_Y,
  getLensBounds, intersects, resolveSnapTarget
} from "./liquidGlass/targets";
import { stepSpring, type SpringValue } from "./liquidGlass/motion";
import { createMagneticController, affectsMagneticTargets } from "./liquidGlass/magnetism";
import { rasterizePortal } from "./liquidGlass/sceneRaster";
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
    const dpr = Math.min(
      Math.max(1, Math.min(window.devicePixelRatio || 1, 1.75)),
      renderer.maxTextureSize / Math.max(window.innerWidth, window.innerHeight, 1),
    );
    const resizeSurfaces = (cssWidth: number, cssHeight: number) => {
      const nextWidth = Math.max(1, Math.round(cssWidth * dpr));
      const nextHeight = Math.max(1, Math.round(cssHeight * dpr));
      if (canvas.width === nextWidth && canvas.height === nextHeight) return false;
      for (const target of [canvas, capture, scratch]) {
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
    let chartLens = false;
    let raf = 0;
    let lastTime = performance.now();
    let lastCapture = 0;
    let lastRoiLeft = Number.NaN;
    let lastRoiTop = Number.NaN;
    let rasterDirty = true;
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
      () => {textureReady=false;lastRoiLeft=Number.NaN;lastRoiTop=Number.NaN;},
    );

    const x: SpringValue = { value: pointerX, velocity: 0, target: pointerX };
    const y: SpringValue = { value: pointerY + FREE_OFFSET_Y, velocity: 0, target: pointerY + FREE_OFFSET_Y };
    const width: SpringValue = { value: BASE_WIDTH, velocity: 0, target: BASE_WIDTH };
    const height: SpringValue = { value: BASE_HEIGHT, velocity: 0, target: BASE_HEIGHT };
    const snap: SpringValue = { value: 0, velocity: 0, target: 0 };

    const magnetism = createMagneticController(
      root,
      () => ({x:pointerX,y:pointerY,inside:pointerInside}),
      () => activeTarget,
      () => {rasterDirty=true;snapDirty=true;},
    );

    // Chart mode changes the original glass geometry, not its rendering layer.
    // Keep native graph hit-testing intact and prioritize actual controls.
    const updateChartLens = () => {
      const element = document.elementFromPoint(pointerX, pointerY);
      const next = pointerInside && Boolean(element?.closest(CHART_LENS_SELECTOR)) &&
        !Boolean(element?.closest("button, a, input, textarea, select, [contenteditable='true'], [data-liquid-snap='false']"));
      if (next === chartLens) return;
      chartLens = next;
      snapDirty = true;
      rasterDirty = true;
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
      } else if (chartLens) {
        // Unlike the offset freeform cursor, a circular lens stays centered
        // exactly beneath the pointer; the same shader samples the same ROI.
        x.target = Math.max(CHART_LENS_SIZE / 2 + 4, Math.min(window.innerWidth - CHART_LENS_SIZE / 2 - 4, pointerX));
        y.target = Math.max(CHART_LENS_SIZE / 2 + 4, Math.min(window.innerHeight - CHART_LENS_SIZE / 2 - 4, pointerY));
        width.target = CHART_LENS_SIZE;
        height.target = CHART_LENS_SIZE;
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

    const uploadTexture = (roiLeft: number, roiTop: number, now: number) => {
      const moved = Math.abs(roiLeft - lastRoiLeft) >= 0.75 || Math.abs(roiTop - lastRoiTop) >= 0.75;
      if (!rasterDirty && !moved) return;
      // The ROI and the uploaded pixels are an atomic pair: never apply a new
      // coordinate origin to an old texture. Moving to a new ROI bypasses the
      // ordinary 32ms stationary-cache throttle.
      const minCaptureInterval = activeTarget ? 16 : 32;
      if (!moved && !urgentCapture && now - lastCapture < minCaptureInterval) return;
      lastCapture = now;
      if (!rasterizePortal(root, capture, scratch, null, roiLeft, roiTop, roi.state.width, roi.state.height, dpr)) {
        textureReady = false;
        return;
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
      const dt = Math.min(0.032, Math.max(0.001, (now - lastTime) / 1000));
      lastTime = now;
      const magneticSettled = magnetism.update(dt);
      updateChartLens();
      updateTargets();

      const snapping = Boolean(activeTarget) || snap.target > 0.001;
      stepSpring(x, dt, snapping ? 300 : 500, snapping ? 25 : 60);
      stepSpring(y, dt, snapping ? 300 : 500, snapping ? 25 : 60);
      stepSpring(width, dt, snapping ? 235 : 310, snapping ? 19 : 32);
      stepSpring(height, dt, snapping ? 235 : 310, snapping ? 19 : 32);
      stepSpring(snap, dt, 220, 18);
      // Firm compression on contact, then one softer elastic release.
      stepSpring(pressure, dt, pressed ? 620 : 400, pressed ? 38 : 23);
      const deformation = Math.max(-0.22, Math.min(1.08, pressure.value));

      roi.update(x.value,y.value,width.value,height.value,activeTarget,snap.value);
      uploadTexture(roi.state.left, roi.state.top, now);

      const hasSample = textureReady && Number.isFinite(lastRoiLeft) && Number.isFinite(lastRoiTop);
      canvas.style.transform = `translate3d(${lastRoiLeft}px, ${lastRoiTop}px, 0)`;
      dot.style.transform = `translate3d(${pointerX - 1.75}px, ${pointerY - 1.75}px, 0)`;
      canvas.style.opacity = pointerInside && hasSample ? "1" : "0";
      dot.style.opacity = pointerInside ? (snap.value > 0.4 ? ".42" : ".86") : "0";

      if (hasSample) {
        const pressWeight = Math.max(0, Math.min(1, deformation));
        const releaseWeight = Math.max(0, -deformation);
        const brandSurface = Boolean(activeTarget?.matches(".brand-home-link, .mobile-brand-home"));
        const readingSurface = Boolean(activeTarget?.matches(".ta-global-search, input, textarea, select, [contenteditable='true']"));
        // Brand lettering is a high-contrast texture. Keep its single optical
        // lens generously framed, with restrained refraction and nearly no
        // chromatic splitting instead of applying the stronger button preset.
        const strength = chartLens ? 0.78
          : brandSurface ? 0.43 + 0.10 * pressWeight
          : readingSurface ? 0.68 + 0.18 * pressWeight
          : (0.95 + (1.14 - 0.95) * snap.value) + 0.62 * pressWeight;
        const pinch = chartLens ? 8.1 : brandSurface ? 8.1 : (7.7 + (7.35 - 7.7) * snap.value) - 0.85 * pressWeight;
        const aberration = chartLens ? 0.055 : brandSurface ? 0.015 : readingSurface ? 0.045 : 0.10 + (0.13 - 0.10) * Math.max(snap.value, pressWeight);
        const zoom = chartLens ? 1.48
          : brandSurface ? 1.007 + 0.005 * pressWeight
          : readingSurface ? 1 + 0.015 * snap.value + 0.012 * pressWeight
          : 1 + 0.055 * snap.value + 0.025 * pressWeight;
        const wobble = chartLens ? 0.025 : brandSurface ? 0.022 + 0.012 * pressWeight : 0.12 + 0.05 * snap.value + 0.06 * pressWeight + 0.18 * releaseWeight;

        renderer.render({
          canvasWidth:canvas.width,canvasHeight:canvas.height,
          x:x.value,y:y.value,
          width:width.value * (1 + 0.025 * deformation),
          height:height.value * (1 - 0.085 * deformation),
          roiLeft:lastRoiLeft,roiTop:lastRoiTop,dpr,
          strength,pinch,aberration,zoom,wobble,time:now/1000,
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
        magneticSettled;

      // Pointer/input/layout events wake the loop. A stationary cursor does
      // not need continuous DOM measurements and WebGL draws once springs settle.
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
        if (node.closest("[data-powerbid-liquid-cursor='true']")) continue;
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
      if (signature !== lastSceneSignature || (animating && now - lastCapture >= DYNAMIC_SCENE_CHECK_MS)) {
        lastSceneSignature = signature;
        rasterDirty = true;
        ensureFrame();
      }
      if (signature || animating) sceneTimer = window.setTimeout(checkDynamicScene, DYNAMIC_SCENE_CHECK_MS);
    };
    const watchScene = () => {
      if (pointerInside && !sceneTimer) sceneTimer = window.setTimeout(checkDynamicScene, DYNAMIC_SCENE_CHECK_MS);
    };
    const onSceneAnimation = (event: Event) => {
      if (!(event.target instanceof Element) ||
          event.target.closest("[data-powerbid-liquid-cursor='true']")) return;
      const bounds = event.target.getBoundingClientRect();
      // Decorative animations elsewhere in the dashboard must not trigger
      // endless ROI redraws. Include a generous outer margin so transitions
      // entering the sampled region are still observed.
      const margin = 120;
      if (Number.isFinite(roi.state.left) && Number.isFinite(roi.state.top) &&
          !intersects(bounds, roi.state.left - margin, roi.state.top - margin,
            roi.state.width + margin * 2, roi.state.height + margin * 2)) return;
      animationWatchUntil = Math.max(animationWatchUntil, performance.now() + 1400);
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
          Boolean(event.target.closest(".recharts-wrapper, .ta-supply-chart, .ta-bars, .ta-gauge-wrap, .pmss-chart"))) {
        rasterDirty = true;
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
      pressed = false;
      pressure.target = 0;
      activeTarget = null;
      snap.target = 0;
      snapDirty = true;
      lastSceneSignature = "";
      animationWatchUntil = 0;
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
      roi.clearLock(); rasterDirty = true;urgentCapture=true; snapDirty = true; wake(); watchScene();
    };
    // Editing changes input.value without mutating DOM text or attributes.
    const handleInput = () => { rasterDirty = true;urgentCapture=true; wake(); };
    const handleResize = () => {
      roi.reset();
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
      if (updates.some(affectsMagneticTargets)) {
        magnetism.refresh();
        snapDirty = true;
      }
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
    const resizeObserver = new ResizeObserver(() => { rasterDirty = true; snapDirty = true; wake(); });
    resizeObserver.observe(root);

    document.fonts?.ready.then(() => { rasterDirty = true; wake(); }).catch(() => {});

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
