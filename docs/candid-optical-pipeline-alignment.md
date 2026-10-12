# Candid-inspired optical capture quality alignment

The PowerBid lens remains our independent, single-WebGL implementation. The
published Framer/Candid demo was inspected as a behavioral reference, not
copied wholesale (it includes site-specific Framer code).

## Actual improvements

- ROI-aware capture density: measure the region currently sampled, not the
  entire window width; desktop capture up to 2x, mobile to 1.5x, with
  supersampling at low-DPI desktop for sharp glyph contours.
- Explicit texture budgets: cap by GPU MAX_TEXTURE_SIZE and a 3.2M-pixel
  backing-image budget; floor rather than round scale to avoid GPU overflow.
- Adaptive performance: 12 consecutive slow frames (>40ms) lower
  capture quality temporarily; 100 fast frames restore it. Hidden tabs,
  debugger pauses and a single spike cannot unexpectedly downscale the lens.
- Atomic texture lifecycle: density changes reset capture, scratch,
  cached backdrop and WebGL texture together. Never pair a new ROI/scale
  with the previous uploaded scene.
- Text fidelity: remove fillText(maxWidth) from DOM Range reconstruction.
  maxWidth squashes glyph contours instead of reproducing CSS text layout.
  Retain the actual font size, glyph proportions, blur, aberration, reflections
  and liquid distortion in the original Shader.
- High-DPI resize: re-read devicePixelRatio on viewport resize/browser
  zoom; retain mobile/GPU constraints.

## Non-goals & limitations

- Do not duplicate Framer's private/editor sources, mouse markup, or animations.
- Do not replace WebGL with CSS backdrop-filter; preserve existing dispersion,
  deliberate ghosting, chromatic distortion, curved borders, zoom and wobble.
- DOM/CSS reconstruction cannot reproduce all compositor effects, videos,
  cross-origin pixels, and complex nested stacking contexts. Tests are needed
  on representative PowerBid charts rather than declaring pixel-level parity.
- GPU resource allocations should not fluctuate on every cursor animation
  frame; quality governor uses sustained frame budgets/hysteresis.

## Validation

Run npm run build and npm run test:workflow, plus desktop-browser pointer tests
over blank canvas, chart, tooltip, snapped controls, scroll, fast route
switches and WebGL context recovery. Validate image sharpness/ROI alignment
at devicePixelRatio 1 and 2; judge visual quality with the intended aberration
effects enabled.
