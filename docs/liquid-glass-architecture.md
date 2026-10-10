# PowerBid liquid-glass cursor architecture

This implementation deliberately keeps **one** optical canvas and **one** WebGL
renderer. No copy of Framer's protected editor sources and no extra cursor
layer are used.

## Modules and ownership

- \`LiquidGlassCursor.tsx\`: React lifecycle, pointer event handling, animation loop, cross-subsystem orchestration.
- \`liquidGlass/targets.ts\`: hit testing, chart-mode detection selectors, snapped target eligibility and visible DOM bounds.
- \`liquidGlass/magnetism.ts\`: small-control springs, CSS translations, low-cost magnetic target registry, selective invalidation.
- \`liquidGlass/motion.ts\`: frame-independent springs.
- \`liquidGlass/roi.ts\`: the sampled region's viewport coordinates, snapped sizing and hysteresis. Owns no GPU state.
- \`liquidGlass/sceneRaster.ts\`: DOM/SVG/text/image to local Canvas backing texture. Uses screen rect minus ROI origin.
- \`liquidGlass/shader.ts\`: unchanged optical GLSL shape, refraction and dispersion.
- \`liquidGlass/renderer.ts\`: owns GL context, buffers, program, texture, upload, draw and disposal.

## Invariants

1. Hit testing, magnetic visual positions and ROI origin use **viewport CSS pixels**.
2. The scene raster converts CSS pixels to ROI-relative coordinates exactly once;
   WebGL converts both lens center and lens dimensions to device pixels.
3. The sampled ROI origin only advances alongside its uploaded image. The canvas
   is positioned with the last successfully uploaded ROI coordinates; a moved
   ROI skips the ordinary static-scene upload throttle.
4. No raster or DOM observer may include \`[data-powerbid-liquid-cursor=true]\`
   in its captured backdrop (avoids recursion).
5. Scene changes trigger dirty updates; stationary, settled content reuses the
   existing texture. Changes to chart SVG nodes should not rescan all magnetic controls.
6. WebGL resources are disposed on unmount and rebuilt after context restoration.
7. Accessibility stays intact: the overlay is pointer-events:none; ordinary controls
   retain native hit testing, and coarse/reduced-motion users do not render the effect.

## Regression matrix before deployment

- Pointer over blank workbench, logo, menu, search control, capacity gauge,
  Recharts chart, tooltip, PMSS graph and modal.
- Scroll and fast page switches while pointer remains stationary.
- Enter/exit circular chart mode; check lens size and actual WebGL center.
- Resize between desktop and tablet; test RTL/text inputs and large snapped buttons.
- Verify canvas resource cleanup and WebGL context loss/recovery.
- Confirm no old screenshot layer, wrong ROI origin or chart active-dot animation.
- Record GPU uploads during idle and movement, and compare with the prior build.

The optical GLSL and existing visual calibration should not be changed as part
of this refactor. Additional effects require their own independent regression.
