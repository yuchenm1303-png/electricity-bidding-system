import { useEffect, useRef } from "react";

const FREE_ROI_SIZE = 420;
const SNAP_ROI_PADDING = 160;
const MAX_ROI_SIZE = 1200;
const BASE_WIDTH = 80;
const BASE_HEIGHT = 54;
const FREE_OFFSET_Y = -32;
const SNAP_DISTANCE = 10;
const RELEASE_DISTANCE = 15;
const FREE_ROI_PADDING = 64;
const ROI_DEADZONE = 35;

// Only *actions* own a lens. Icons/text inside a button, the brand lockup,
// metric values, form fields and chart geometry must not compete as targets.
const SNAP_SELECTOR = [
  ".sidebar-collapse", ".nav-entry", ".ta-menu-toggle", ".ta-header-icon",
  ".app button:not(:disabled):not(.mobile-backdrop):not(.ta-settings-overlay)",
  ".app a[href]:not(.brand-home-link)",
  "[data-liquid-snap='true']",
].join(",");

// Magnetic translation belongs to small buttons, never to form controls,
// graphics, entire cards or layout containers. Wide controls can still get
// the lens, but stay in place so text layout and hit areas remain stable.
const MAGNETIC_SELECTOR = [
  ".sidebar-collapse", ".nav-entry", ".ta-menu-toggle", ".ta-header-icon",
  ".app button:not(:disabled):not(.mobile-backdrop):not(.ta-settings-overlay)",
  ".app a[href]:not(.brand-home-link)",
  "[data-magnetic-hover='true']",
].join(",");

const EDITABLE_SELECTOR = "input, textarea, select, [contenteditable='true'], [role='slider']";
const EXCLUDED_SURFACE_SELECTOR = ".brand-home-link, .table-search, [data-liquid-snap='false']";
const GENERAL_LENS_MAX_WIDTH = 186;
const GENERAL_LENS_MAX_HEIGHT = 68;
const MIN_LENS_WIDTH = 42;
const MIN_LENS_HEIGHT = 36;

function isEligibleSurface(element: HTMLElement) {
  if (element.matches(":disabled") || element.closest("[aria-hidden='true']")) return false;
  if (element.matches(EDITABLE_SELECTOR) || element.closest(EXCLUDED_SURFACE_SELECTOR)) return false;
  // Search suggestion *buttons* can snap; the surrounding search field cannot.
  if (element.closest(".ta-global-search") && !element.closest(".ta-search-results")) return false;
  const style = getComputedStyle(element);
  if (style.pointerEvents === "none" || style.visibility !== "visible" || style.display === "none") return false;
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 &&
    rect.right > 0 && rect.bottom > 0 &&
    rect.left < window.innerWidth && rect.top < window.innerHeight;
}

function getLensBounds(element: HTMLElement, pointerX: number, pointerY: number) {
  const rect = element.getBoundingClientRect();
  const compact = element.matches(".sidebar-collapse, .ta-menu-toggle, .ta-header-icon, .icon-button");
  const navigation = element.matches(".nav-entry");
  const padding = compact ? 6 : 8;
  const maxWidth = compact ? 66 : navigation ? 186 : GENERAL_LENS_MAX_WIDTH;
  const maxHeight = compact ? 62 : navigation ? 60 : GENERAL_LENS_MAX_HEIGHT;
  const width = Math.min(window.innerWidth - 16, Math.max(MIN_LENS_WIDTH, Math.min(rect.width + 2 * padding, maxWidth)));
  const height = Math.min(window.innerHeight - 16, Math.max(MIN_LENS_HEIGHT, Math.min(rect.height + 2 * padding, maxHeight)));
  // Very wide interactive rows receive a local lens at the real pointer
  // position, not a giant glass sheet anchored in the middle of the row.
  const centerX = rect.width > width + 16
    ? Math.max(rect.left + width / 2, Math.min(rect.right - width / 2, pointerX))
    : rect.left + rect.width / 2;
  const centerY = rect.height > height + 16
    ? Math.max(rect.top + height / 2, Math.min(rect.bottom - height / 2, pointerY))
    : rect.top + rect.height / 2;
  return {
    width,
    height,
    centerX: Math.max(width / 2 + 3, Math.min(window.innerWidth - width / 2 - 3, centerX)),
    centerY: Math.max(height / 2 + 3, Math.min(window.innerHeight - height / 2 - 3, centerY)),
  };
}

type SpringValue = { value: number; velocity: number; target: number };

function stepSpring(spring: SpringValue, dt: number, stiffness: number, damping: number) {
  const acceleration = (spring.target - spring.value) * stiffness;
  spring.velocity += acceleration * dt;
  spring.velocity *= Math.exp(-damping * dt);
  spring.value += spring.velocity * dt;
}

function rectDistance(rect: DOMRect, x: number, y: number) {
  const dx = Math.max(rect.left - x, 0, x - rect.right);
  const dy = Math.max(rect.top - y, 0, y - rect.bottom);
  return Math.hypot(dx, dy);
}

function intersects(rect: DOMRect, left: number, top: number, width: number, height: number) {
  return rect.right >= left && rect.left <= left + width && rect.bottom >= top && rect.top <= top + height;
}

function cssNumber(value: string, fallback = 0) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function radiusFromStyle(style: CSSStyleDeclaration, rect: DOMRect) {
  const raw = style.borderTopLeftRadius || "0";
  if (raw.includes("%")) return Math.min(rect.width, rect.height) * cssNumber(raw) / 100;
  return Math.min(cssNumber(raw), Math.min(rect.width, rect.height) / 2);
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  const r = Math.max(0, Math.min(radius, width / 2, height / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function visibleColor(value: string) {
  return value !== "transparent" && value !== "rgba(0, 0, 0, 0)" && value !== "rgba(0,0,0,0)";
}

function safeImageForCanvas(img: HTMLImageElement) {
  if (!img.complete || img.naturalWidth <= 0 || img.naturalHeight <= 0) return false;
  try {
    const url = new URL(img.currentSrc || img.src, window.location.href);
    return url.origin === window.location.origin || img.crossOrigin === "anonymous";
  } catch {
    return false;
  }
}

function drawImageFit(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  rect: DOMRect,
  style: CSSStyleDeclaration,
  roiLeft: number,
  roiTop: number,
) {
  const fit = style.objectFit || "fill";
  const boxX = rect.left - roiLeft;
  const boxY = rect.top - roiTop;
  let sx = 0;
  let sy = 0;
  let sw = img.naturalWidth;
  let sh = img.naturalHeight;

  let drawX = boxX;
  let drawY = boxY;
  let drawWidth = rect.width;
  let drawHeight = rect.height;
  const boxRatio = rect.width / Math.max(rect.height, 1);
  const imageRatio = img.naturalWidth / Math.max(img.naturalHeight, 1);

  if (fit === "contain" || fit === "scale-down") {
    // contain must LETTERBOX rather than crop: the old rasterizer stretched
    // the Smirel logo, producing a doubled/misaligned refracted wordmark.
    const scale = fit === "scale-down"
      ? Math.min(1, Math.min(rect.width / img.naturalWidth, rect.height / img.naturalHeight))
      : Math.min(rect.width / img.naturalWidth, rect.height / img.naturalHeight);
    drawWidth = img.naturalWidth * scale;
    drawHeight = img.naturalHeight * scale;
    drawX += (rect.width - drawWidth) / 2;
    drawY += (rect.height - drawHeight) / 2;
  } else if (fit === "cover") {
    if (imageRatio > boxRatio) {
      sw = img.naturalHeight * boxRatio;
      sx = (img.naturalWidth - sw) / 2;
    } else {
      sh = img.naturalWidth / boxRatio;
      sy = (img.naturalHeight - sh) / 2;
    }
  }

  try {
    ctx.drawImage(img, sx, sy, sw, sh, drawX, drawY, drawWidth, drawHeight);
  } catch {
    // Skip any image the browser refuses to expose to canvas.
  }
}

// PowerBid-only background adapter. The original Loom background image
// has no counterpart here; the original shader and raster traversal follow.
function drawWallpaper(
  ctx: CanvasRenderingContext2D,
  _image: HTMLImageElement | null,
  _roiLeft: number,
  _roiTop: number,
  _viewportWidth: number,
  _viewportHeight: number,
  roiWidth: number,
  roiHeight: number,
) {
  const app = document.querySelector<HTMLElement>(".app");
  const appBackground = app ? getComputedStyle(app).backgroundColor : "";
  const bodyBackground = getComputedStyle(document.body).backgroundColor;
  ctx.fillStyle = visibleColor(appBackground) ? appBackground :
    visibleColor(bodyBackground) ? bodyBackground : "#f9fafb";
  ctx.fillRect(0, 0, roiWidth, roiHeight);
}

function drawTextNode(
  ctx: CanvasRenderingContext2D,
  node: Text,
  style: CSSStyleDeclaration,
  roiLeft: number,
  roiTop: number,
  roiWidth: number,
  roiHeight: number,
  inheritedOpacity: number,
) {
  const value = node.data;
  if (!value.trim()) return;
  const color = style.color;
  if (!visibleColor(color)) return;
  const matches = Array.from(value.matchAll(/\S+\s*/g)).slice(0, 80);
  if (!matches.length) return;

  ctx.save();
  ctx.globalAlpha = inheritedOpacity;
  ctx.fillStyle = color;
  ctx.font = `${style.fontStyle || "normal"} ${style.fontWeight || "400"} ${style.fontSize || "16px"} ${style.fontFamily || "sans-serif"}`;
  ctx.textBaseline = "alphabetic";
  const letterAware = ctx as CanvasRenderingContext2D & { letterSpacing?: string };
  if ("letterSpacing" in letterAware) letterAware.letterSpacing = style.letterSpacing;

  const transform = style.textTransform;
  for (const match of matches) {
    const index = match.index ?? 0;
    const end = Math.min(value.length, index + match[0].length);
    const range = document.createRange();
    try {
      range.setStart(node, index);
      range.setEnd(node, end);
      for (const rect of Array.from(range.getClientRects())) {
        if (!intersects(rect, roiLeft, roiTop, roiWidth, roiHeight)) continue;
        let text = match[0].replace(/\s+$/g, "");
        if (!text) continue;
        if (transform === "uppercase") text = text.toUpperCase();
        if (transform === "lowercase") text = text.toLowerCase();
        if (transform === "capitalize") text = text.replace(/\b\w/g, (part) => part.toUpperCase());
        ctx.fillText(text, rect.left - roiLeft, rect.top - roiTop + rect.height * 0.8, Math.max(rect.width + 2, 1));
      }
    } catch {
      // React may update a text node between range reads.
    } finally {
      range.detach();
    }
  }
  ctx.restore();
}

function drawSvgIcon(ctx: CanvasRenderingContext2D, svg: SVGSVGElement, roiLeft: number, roiTop: number, opacity: number) {
  for (const shape of Array.from(svg.querySelectorAll<SVGGeometryElement>("path, rect, circle, ellipse, line, polyline, polygon"))) {
    const style = getComputedStyle(shape);
    const matrix = shape.getScreenCTM();
    if (!matrix || style.display === "none" || style.visibility === "hidden") continue;
    const number = (name: string) => cssNumber(shape.getAttribute(name) ?? "0");
    const path = new Path2D(shape.tagName === "path" ? shape.getAttribute("d") ?? "" : undefined);
    switch (shape.tagName) {
      case "rect": path.roundRect(number("x"), number("y"), number("width"), number("height"), { x: number("rx"), y: shape.hasAttribute("ry") ? number("ry") : number("rx") }); break;
      case "circle": path.arc(number("cx"), number("cy"), number("r"), 0, Math.PI * 2); break;
      case "ellipse": path.ellipse(number("cx"), number("cy"), number("rx"), number("ry"), 0, 0, Math.PI * 2); break;
      case "line": path.moveTo(number("x1"), number("y1")); path.lineTo(number("x2"), number("y2")); break;
      case "polyline":
      case "polygon": {
        const points = (shape as SVGPolylineElement).points;
        for (let i = 0; i < points.numberOfItems; i++) {
          const point = points.getItem(i);
          if (i === 0) path.moveTo(point.x, point.y);
          else path.lineTo(point.x, point.y);
        }
        if (shape.tagName === "polygon") path.closePath();
        break;
      }
    }
    ctx.save();
    ctx.translate(-roiLeft, -roiTop);
    ctx.transform(matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f);
    let alpha = opacity;
    for (let element: Element | null = shape; element && element !== svg; element = element.parentElement) {
      alpha *= cssNumber(getComputedStyle(element).opacity, 1);
    }
    ctx.globalAlpha = alpha * cssNumber(style.fillOpacity, 1);
    if (style.fill !== "none") {
      ctx.fillStyle = style.fill === "currentcolor" ? style.color : style.fill;
      ctx.fill(path, style.fillRule === "evenodd" ? "evenodd" : "nonzero");
    }
    if (style.stroke !== "none") {
      ctx.globalAlpha = alpha * cssNumber(style.strokeOpacity, 1);
      ctx.strokeStyle = style.stroke === "currentcolor" ? style.color : style.stroke;
      ctx.lineWidth = cssNumber(style.strokeWidth, 1);
      ctx.lineCap = style.strokeLinecap as CanvasLineCap;
      ctx.lineJoin = style.strokeLinejoin as CanvasLineJoin;
      ctx.miterLimit = cssNumber(style.strokeMiterlimit, 4);
      ctx.setLineDash(style.strokeDasharray === "none" ? [] : style.strokeDasharray.split(/[ ,]+/).map(value => cssNumber(value)));
      ctx.lineDashOffset = cssNumber(style.strokeDashoffset);
      ctx.stroke(path);
    }
    ctx.restore();
  }
}

function parseBackdropBlur(style: CSSStyleDeclaration) {
  const extended = style as CSSStyleDeclaration & { webkitBackdropFilter?: string };
  const raw = style.backdropFilter || extended.webkitBackdropFilter || "";
  const match = raw.match(/blur\(([\d.]+)px\)/i);
  return match ? Math.min(24, cssNumber(match[1])) : 0;
}

function rasterizePortal(
  root: HTMLElement,
  canvas: HTMLCanvasElement,
  scratch: HTMLCanvasElement,
  wallpaper: HTMLImageElement | null,
  roiLeft: number,
  roiTop: number,
  roiWidth: number,
  roiHeight: number,
  dpr: number,
) {
  const ctx = canvas.getContext("2d", { alpha: true });
  const scratchCtx = scratch.getContext("2d", { alpha: true });
  if (!ctx || !scratchCtx) return false;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  drawWallpaper(ctx, wallpaper, roiLeft, roiTop, window.innerWidth, window.innerHeight, roiWidth, roiHeight);

  const content = root.querySelector<HTMLElement>(".app") ?? root;

  const renderElement = (el: HTMLElement, parentOpacity: number) => {
    if (el.dataset.powerbidLiquidCursor === "true" || el.closest("[data-powerbid-liquid-cursor='true']")) return;
    if (el.closest(".cosmos") || el.classList.contains("beach-wallpaper")) return;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return;
    const ownOpacity = Math.max(0, Math.min(1, cssNumber(style.opacity, 1)));
    const opacity = parentOpacity * ownOpacity;
    if (opacity <= 0.002) return;

    const rect = el.getBoundingClientRect();
    if (!intersects(rect, roiLeft, roiTop, roiWidth, roiHeight)) return;

    const localX = rect.left - roiLeft;
    const localY = rect.top - roiTop;
    const radius = radiusFromStyle(style, rect);
    const blur = parseBackdropBlur(style);

    if (blur > 0 && (el.classList.contains("cards") || el.classList.contains("loom-host-onboarding"))) {
      scratchCtx.setTransform(1, 0, 0, 1, 0, 0);
      scratchCtx.clearRect(0, 0, scratch.width, scratch.height);
      scratchCtx.filter = `blur(${Math.max(1, blur * dpr)}px)`;
      scratchCtx.drawImage(canvas, 0, 0);
      scratchCtx.filter = "none";
      ctx.save();
      roundedRect(ctx, localX, localY, rect.width, rect.height, radius);
      ctx.clip();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = opacity;
      ctx.drawImage(scratch, 0, 0);
      ctx.restore();
    }

    if (visibleColor(style.backgroundColor)) {
      ctx.save();
      ctx.globalAlpha = opacity;
      ctx.fillStyle = style.backgroundColor;
      roundedRect(ctx, localX, localY, rect.width, rect.height, radius);
      ctx.fill();
      ctx.restore();
    }

    const borderWidth = Math.max(
      cssNumber(style.borderTopWidth),
      cssNumber(style.borderRightWidth),
      cssNumber(style.borderBottomWidth),
      cssNumber(style.borderLeftWidth),
    );
    if (borderWidth > 0 && style.borderTopStyle !== "none" && visibleColor(style.borderTopColor)) {
      ctx.save();
      ctx.globalAlpha = opacity;
      ctx.strokeStyle = style.borderTopColor;
      ctx.lineWidth = borderWidth;
      roundedRect(
        ctx,
        localX + borderWidth / 2,
        localY + borderWidth / 2,
        Math.max(0, rect.width - borderWidth),
        Math.max(0, rect.height - borderWidth),
        Math.max(0, radius - borderWidth / 2),
      );
      ctx.stroke();
      ctx.restore();
    }

    if (el instanceof HTMLImageElement && safeImageForCanvas(el)) {
      ctx.save();
      ctx.globalAlpha = opacity;
      drawImageFit(ctx, el, rect, style, roiLeft, roiTop);
      ctx.restore();
    }

    const textInput = el instanceof HTMLTextAreaElement ||
      (el instanceof HTMLInputElement && !["range", "checkbox", "radio", "button", "submit", "reset", "color", "file", "hidden", "image"].includes(el.type));
    if (textInput && (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) {
      const placeholder = !el.value;
      const text = el instanceof HTMLInputElement && el.type === "password"
        ? (el.value ? "•".repeat(el.value.length) : el.placeholder)
        : el.value || el.placeholder;
      // Text inputs clip their own content. fillText(maxWidth) does NOT clip:
      // it squeezes the entire placeholder until it resembles duplicate text.
      if (text) {
        const leftInset = cssNumber(style.borderLeftWidth) + cssNumber(style.paddingLeft);
        const rightInset = cssNumber(style.borderRightWidth) + cssNumber(style.paddingRight);
        const clipWidth = Math.max(0, rect.width - leftInset - rightInset);
        const placeholderColor = placeholder ? getComputedStyle(el, "::placeholder").color : "";
        ctx.save();
        ctx.beginPath();
        ctx.rect(localX + leftInset, localY + 1, clipWidth, Math.max(0, rect.height - 2));
        ctx.clip();
        ctx.globalAlpha = opacity;
        ctx.fillStyle = placeholder && visibleColor(placeholderColor) ? placeholderColor : style.color;
        ctx.font = `${style.fontStyle || "normal"} ${style.fontWeight || "400"} ${style.fontSize || "16px"} ${style.fontFamily || "sans-serif"}`;
        ctx.textBaseline = "middle";
        ctx.fillText(text, localX + leftInset - el.scrollLeft, localY + rect.height / 2);
        ctx.restore();
      }
    }

    // Honor native overflow clipping for descendants (search rows, badges,
    // compact navigation). Otherwise refracted text escapes its actual box.
    const clipsChildren = ["hidden", "clip", "auto", "scroll"].includes(style.overflowX) ||
      ["hidden", "clip", "auto", "scroll"].includes(style.overflowY);
    if (clipsChildren) {
      ctx.save();
      roundedRect(ctx, localX, localY, rect.width, rect.height, radius);
      ctx.clip();
    }
    for (const child of Array.from(el.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        drawTextNode(ctx, child as Text, style, roiLeft, roiTop, roiWidth, roiHeight, opacity);
      } else if (child instanceof HTMLElement) {
        renderElement(child, opacity);
      } else if (child instanceof SVGSVGElement) {
        const svgStyle = getComputedStyle(child);
        if (svgStyle.display !== "none" && svgStyle.visibility !== "hidden" && intersects(child.getBoundingClientRect(), roiLeft, roiTop, roiWidth, roiHeight)) {
          drawSvgIcon(ctx, child, roiLeft, roiTop, opacity * cssNumber(svgStyle.opacity, 1));
        }
      }
    }
    if (clipsChildren) ctx.restore();
  };

  renderElement(content, 1);
  return true;
}

function createShader(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.warn("PowerBid liquid cursor shader failed:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}


function createProgram(gl: WebGLRenderingContext) {
  const vertex = createShader(gl, gl.VERTEX_SHADER, `
    attribute vec2 a_position;
    attribute vec2 a_uv;
    varying vec2 v_uv;
    void main() {
      v_uv = a_uv;
      gl_Position = vec4(a_position, 0.0, 1.0);
    }
  `);
  const fragment = createShader(gl, gl.FRAGMENT_SHADER, `
    precision highp float;
    varying vec2 v_uv;
    uniform sampler2D u_texture;
    uniform vec2 u_resolution;
    uniform vec2 u_lensCenter;
    uniform vec2 u_lensSize;
    uniform float u_strength;
    uniform float u_pinch;
    uniform float u_aberration;
    uniform float u_zoom;
    uniform float u_wobble;
    uniform float u_time;

    float sdRoundBox(vec2 p, vec2 b, float r) {
      vec2 q = abs(p) - b + vec2(r);
      return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
    }

    vec2 warpPoint(vec2 p, float radius) {
      float angle = atan(p.y, p.x);
      float wave =
        sin(angle * 3.0 + u_time * 1.7) * 0.46 +
        cos(angle * 5.0 - u_time * 2.3) * 0.28 +
        sin(angle * 7.0 + u_time * 3.1) * 0.16;
      vec2 radial = normalize(p + vec2(0.0001));
      vec2 tangent = vec2(-radial.y, radial.x);
      return p - radial * wave * u_wobble * radius * 0.055
               + tangent * sin(angle * 2.0 + u_time * 1.25) * u_wobble * radius * 0.012;
    }

    void main() {
      vec2 screenUv = vec2(v_uv.x, 1.0 - v_uv.y);
      vec2 pixel = screenUv * u_resolution;
      vec2 halfSize = max(u_lensSize * 0.5, vec2(2.0));
      float radius = max(2.0, min(halfSize.x, halfSize.y));
      vec2 local = warpPoint(pixel - u_lensCenter, radius);
      float d = sdRoundBox(local, halfSize, radius);
      if (d > 1.5) {
        gl_FragColor = vec4(0.0);
        return;
      }

      float e = 1.0;
      float dx = sdRoundBox(local + vec2(e, 0.0), halfSize, radius) - sdRoundBox(local - vec2(e, 0.0), halfSize, radius);
      float dy = sdRoundBox(local + vec2(0.0, e), halfSize, radius) - sdRoundBox(local - vec2(0.0, e), halfSize, radius);
      vec2 normal = normalize(vec2(dx, dy) + vec2(0.00001));
      float distNorm = clamp(1.0 + d / radius, 0.0, 1.0);
      float effectivePinch = u_pinch * (radius / 100.0);
      float displacement = pow(distNorm, max(0.12, effectivePinch)) * u_strength * 40.0;

      // When the lens is physically close to a viewport/capture boundary there is
      // no real off-screen texture to refract. Fade the displacement there instead
      // of CLAMP_TO_EDGE stretching one texture column into a blank-looking slab.
      float textureEdgeDistance = min(
        min(screenUv.x, 1.0 - screenUv.x),
        min(screenUv.y, 1.0 - screenUv.y)
      );
      float edgeSafety = smoothstep(0.012, 0.075, textureEdgeDistance);
      displacement *= edgeSafety;

      vec2 sampleUv = screenUv - normal * (displacement / u_resolution);

      vec2 centerUv = u_lensCenter / u_resolution;
      sampleUv = (sampleUv - centerUv) / max(u_zoom, 1.0) + centerUv;
      sampleUv = clamp(sampleUv, vec2(0.001), vec2(0.999));

      vec2 chroma = normal * u_aberration * 0.02 * distNorm * edgeSafety;
      vec3 color;
      color.r = texture2D(u_texture, clamp(sampleUv + chroma, 0.0, 1.0)).r;
      color.g = texture2D(u_texture, sampleUv).g;
      color.b = texture2D(u_texture, clamp(sampleUv - chroma, 0.0, 1.0)).b;

      // Keep the surface almost optically clear.
      float edge = smoothstep(0.76, 1.0, distNorm);
      vec3 reflected = texture2D(u_texture, clamp(sampleUv + normal * 0.008 * edge, 0.0, 1.0)).rgb;
      color = mix(color, reflected, edge * 0.035);

      vec2 lightDir = normalize(vec2(-0.62, -0.78));
      float directional = pow(max(dot(normal, lightDir), 0.0), 7.0);
      float rim = edge * (0.008 + directional * 0.070);
      color += vec3(0.62, 0.78, 0.88) * rim;

      float mask = 1.0 - smoothstep(-1.15, 0.9, d);
      float edgeGlass = smoothstep(0.90, 1.0, distNorm) * 0.015;
      gl_FragColor = vec4((color + vec3(edgeGlass)) * mask, mask);
    }
  `);
  if (!vertex || !fragment) return null;
  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.warn("PowerBid liquid cursor program failed:", gl.getProgramInfoLog(program));
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

export function LiquidGlassCursor() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const dot = dotRef.current;
    const root = canvas?.closest("#root") as HTMLElement | null;
    if (!canvas || !dot || !root) return;

    const finePointer = window.matchMedia("(pointer: fine)").matches;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!finePointer || reducedMotion) return;

    const gl = canvas.getContext("webgl", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: true,
      preserveDrawingBuffer: false,
    });
    if (!gl) return;
    const program = createProgram(gl);
    if (!program) return;

    const capture = document.createElement("canvas");
    const scratch = document.createElement("canvas");
    const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 1.75));
    let roiWidth = FREE_ROI_SIZE;
    let roiHeight = FREE_ROI_SIZE;

    const resizeSurfaces = (cssWidth: number, cssHeight: number) => {
      const nextWidth = Math.max(1, Math.round(cssWidth * dpr));
      const nextHeight = Math.max(1, Math.round(cssHeight * dpr));
      if (canvas.width === nextWidth && canvas.height === nextHeight) return false;
      for (const target of [canvas, capture, scratch]) {
        target.width = nextWidth;
        target.height = nextHeight;
      }
      canvas.style.width = `${cssWidth}px`;
      canvas.style.height = `${cssHeight}px`;
      return true;
    };

    resizeSurfaces(roiWidth, roiHeight);

    const position = gl.createBuffer();
    const uv = gl.createBuffer();
    const texture = gl.createTexture();
    if (!position || !uv || !texture) return;

    gl.bindBuffer(gl.ARRAY_BUFFER, position);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
    const positionLocation = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, uv);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0,0, 1,0, 0,1, 0,1, 1,0, 1,1]), gl.STATIC_DRAW);
    const uvLocation = gl.getAttribLocation(program, "a_uv");
    gl.enableVertexAttribArray(uvLocation);
    gl.vertexAttribPointer(uvLocation, 2, gl.FLOAT, false, 0, 0);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    const uniforms = {
      texture: gl.getUniformLocation(program, "u_texture"),
      resolution: gl.getUniformLocation(program, "u_resolution"),
      lensCenter: gl.getUniformLocation(program, "u_lensCenter"),
      lensSize: gl.getUniformLocation(program, "u_lensSize"),
      strength: gl.getUniformLocation(program, "u_strength"),
      pinch: gl.getUniformLocation(program, "u_pinch"),
      aberration: gl.getUniformLocation(program, "u_aberration"),
      zoom: gl.getUniformLocation(program, "u_zoom"),
      wobble: gl.getUniformLocation(program, "u_wobble"),
      time: gl.getUniformLocation(program, "u_time"),
    };

    let pointerX = window.innerWidth / 2;
    let pointerY = window.innerHeight / 2;
    let pointerInside = false;
    let pressed = false;
    const pressure: SpringValue = { value: 0, velocity: 0, target: 0 };
    let activeTarget: HTMLElement | null = null;
    let raf = 0;
    let lastTime = performance.now();
    let lastCapture = 0;
    let lastRoiLeft = Number.NaN;
    let lastRoiTop = Number.NaN;
    let roiLeft = Number.NaN;
    let roiTop = Number.NaN;
    let roiLockedTarget: HTMLElement | null = null;
    let snappedRoiWidth = FREE_ROI_SIZE;
    let snappedRoiHeight = FREE_ROI_SIZE;
    let rasterDirty = true;
    let textureReady = false;
    let snapDirty = true;
    let running = false;

    const x: SpringValue = { value: pointerX, velocity: 0, target: pointerX };
    const y: SpringValue = { value: pointerY + FREE_OFFSET_Y, velocity: 0, target: pointerY + FREE_OFFSET_Y };
    const width: SpringValue = { value: BASE_WIDTH, velocity: 0, target: BASE_WIDTH };
    const height: SpringValue = { value: BASE_HEIGHT, velocity: 0, target: BASE_HEIGHT };
    const snap: SpringValue = { value: 0, velocity: 0, target: 0 };

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
      let settled = true;
      for (const element of magneticTargets) {
        const state = magneticStates.get(element);
        if (!state || !element.isConnected) continue;

        const rect = element.getBoundingClientRect();
        const baseLeft = rect.left - state.appliedX;
        const baseTop = rect.top - state.appliedY;
        const baseRight = baseLeft + rect.width;
        const baseBottom = baseTop + rect.height;
        const hoverArea = element.matches(".nav-entry") ? 9 : 11;
        const inside =
          pointerInside &&
          pointerX >= baseLeft - hoverArea &&
          pointerX <= baseRight + hoverArea &&
          pointerY >= baseTop - hoverArea &&
          pointerY <= baseBottom + hoverArea;

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
          rasterDirty = true;
          snapDirty = true;
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

    const findSnapTarget = () => {
      const previous = activeTarget;
      let next: HTMLElement | null = null;
      let bestScore = Number.POSITIVE_INFINITY;
      const topElement = document.elementFromPoint(pointerX, pointerY);
      // Inputs retain the free-moving glass cursor, without a giant focus
      // lens that obscures placeholder, caret or native browser controls.
      if (topElement?.closest(EDITABLE_SELECTOR) ||
          topElement?.closest(".brand-home-link, .table-search") ||
          (topElement?.closest(".ta-global-search") && !topElement.closest(".ta-search-results"))) {
        activeTarget = null;
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
      activeTarget = next;
      return next;
    };

    const updateTargets = () => {
      if (!snapDirty && !activeTarget) return;
      snapDirty = false;
      const previousTarget = activeTarget;
      const target = findSnapTarget();
      if (target !== previousTarget) {
        rasterDirty = true;
        roiLockedTarget = null;
        if (target) {
          const { width: finalLensWidth, height: finalLensHeight } = getLensBounds(target, pointerX, pointerY);
          snappedRoiWidth = Math.min(
            MAX_ROI_SIZE,
            Math.max(FREE_ROI_SIZE, Math.ceil((finalLensWidth + SNAP_ROI_PADDING * 2) / 16) * 16),
          );
          snappedRoiHeight = Math.min(
            MAX_ROI_SIZE,
            Math.max(FREE_ROI_SIZE, Math.ceil((finalLensHeight + SNAP_ROI_PADDING * 2) / 16) * 16),
          );
        }
      }
      if (target) {
        const lens = getLensBounds(target, pointerX, pointerY);
        x.target = lens.centerX;
        y.target = lens.centerY;
        width.target = lens.width;
        height.target = lens.height;
        snap.target = 1;
      } else {
        x.target = pointerX;
        y.target = pointerY + FREE_OFFSET_Y;
        width.target = BASE_WIDTH;
        height.target = BASE_HEIGHT;
        snap.target = 0;
      }
    };

    const updateRoi = (lensX: number, lensY: number, lensWidth: number, lensHeight: number) => {
      const target = activeTarget?.isConnected ? activeTarget : null;
      // Hold the snapped ROI at its final size for the entire morph and release.
      // Resizing the backing canvas while width/height springs are moving invalidates
      // the WebGL texture and was the source of the visible flashing.
      const holdSnappedRoi =
        Boolean(target) ||
        snap.value > 0.025 ||
        lensWidth > BASE_WIDTH + 4 ||
        lensHeight > BASE_HEIGHT + 4;
      const desiredWidth = holdSnappedRoi ? snappedRoiWidth : FREE_ROI_SIZE;
      const desiredHeight = holdSnappedRoi ? snappedRoiHeight : FREE_ROI_SIZE;

      if (!holdSnappedRoi) {
        snappedRoiWidth = FREE_ROI_SIZE;
        snappedRoiHeight = FREE_ROI_SIZE;
      }

      const boundedWidth = Math.max(1, Math.min(window.innerWidth, desiredWidth));
      const boundedHeight = Math.max(1, Math.min(window.innerHeight, desiredHeight));
      if (boundedWidth !== roiWidth || boundedHeight !== roiHeight) {
        roiWidth = boundedWidth;
        roiHeight = boundedHeight;
        if (resizeSurfaces(roiWidth, roiHeight)) {
          textureReady = false;
          lastRoiLeft = Number.NaN;
          lastRoiTop = Number.NaN;
        }
        roiLeft = Number.NaN;
        roiTop = Number.NaN;
        roiLockedTarget = null;
        rasterDirty = true;
      }

      const maxLeft = Math.max(0, window.innerWidth - roiWidth);
      const maxTop = Math.max(0, window.innerHeight - roiHeight);

      if (target) {
        const state = magneticStates.get(target);
        // Lock near the non-magnetic position but RECENTER after scrolling,
        // layout shifts or moving along a long button. A permanent ROI lock
        // used to sample pixels from the wrong part of the interface.
        const bounds = getLensBounds(target, pointerX, pointerY);
        const baseCenterX = bounds.centerX - (state?.appliedX ?? 0);
        const baseCenterY = bounds.centerY - (state?.appliedY ?? 0);
        const nextLeft = Math.round(Math.max(0, Math.min(maxLeft, baseCenterX - roiWidth / 2)));
        const nextTop = Math.round(Math.max(0, Math.min(maxTop, baseCenterY - roiHeight / 2)));
        if (roiLockedTarget !== target || !Number.isFinite(roiLeft) || !Number.isFinite(roiTop) ||
            Math.abs(nextLeft - roiLeft) > 28 || Math.abs(nextTop - roiTop) > 28) {
          roiLeft = nextLeft;
          roiTop = nextTop;
          roiLockedTarget = target;
          rasterDirty = true;
        }
        return;
      }

      roiLockedTarget = null;
      if (!Number.isFinite(roiLeft) || !Number.isFinite(roiTop)) {
        roiLeft = Math.round(Math.max(0, Math.min(maxLeft, lensX - roiWidth / 2)));
        roiTop = Math.round(Math.max(0, Math.min(maxTop, lensY - roiHeight / 2)));
        rasterDirty = true;
        return;
      }

      const halfW = lensWidth / 2;
      const halfH = lensHeight / 2;
      const marginX = Math.max(8, Math.min(FREE_ROI_PADDING, (roiWidth - lensWidth) / 2 - 8));
      const marginY = Math.max(8, Math.min(FREE_ROI_PADDING, (roiHeight - lensHeight) / 2 - 8));
      const minX = roiLeft + halfW + marginX;
      const maxX = roiLeft + roiWidth - halfW - marginX;
      const minY = roiTop + halfH + marginY;
      const maxY = roiTop + roiHeight - halfH - marginY;

      let nextLeft = roiLeft;
      let nextTop = roiTop;
      if (lensX < minX) nextLeft -= Math.max(ROI_DEADZONE, minX - lensX);
      else if (lensX > maxX) nextLeft += Math.max(ROI_DEADZONE, lensX - maxX);
      if (lensY < minY) nextTop -= Math.max(ROI_DEADZONE, minY - lensY);
      else if (lensY > maxY) nextTop += Math.max(ROI_DEADZONE, lensY - maxY);

      nextLeft = Math.round(Math.max(0, Math.min(maxLeft, nextLeft)));
      nextTop = Math.round(Math.max(0, Math.min(maxTop, nextTop)));
      if (nextLeft !== roiLeft || nextTop !== roiTop) {
        roiLeft = nextLeft;
        roiTop = nextTop;
        rasterDirty = true;
      }
    };
    const uploadTexture = (roiLeft: number, roiTop: number, now: number) => {
      const moved = Math.abs(roiLeft - lastRoiLeft) >= 0.75 || Math.abs(roiTop - lastRoiTop) >= 0.75;
      if (!rasterDirty && !moved) return;
      const minCaptureInterval = activeTarget ? 16 : 32;
      if (now - lastCapture < minCaptureInterval) return;
      lastCapture = now;
      lastRoiLeft = roiLeft;
      lastRoiTop = roiTop;
      rasterDirty = false;
      if (!rasterizePortal(root, capture, scratch, null, roiLeft, roiTop, roiWidth, roiHeight, dpr)) return;
      try {
        gl.bindTexture(gl.TEXTURE_2D, texture);
        if (!textureReady) {
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, capture);
          textureReady = true;
        } else {
          gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, capture);
        }
      } catch (error) {
        console.warn("PowerBid liquid cursor texture upload failed:", error);
        textureReady = false;
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
      const magneticSettled = updateMagneticTargets(dt);
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

      updateRoi(x.value, y.value, width.value, height.value);
      uploadTexture(roiLeft, roiTop, now);

      canvas.style.transform = `translate3d(${roiLeft}px, ${roiTop}px, 0)`;
      dot.style.transform = `translate3d(${pointerX - 1.75}px, ${pointerY - 1.75}px, 0)`;
      canvas.style.opacity = pointerInside && textureReady ? "1" : "0";
      dot.style.opacity = pointerInside ? (snap.value > 0.4 ? ".42" : ".86") : "0";

      if (textureReady) {
        const pressWeight = Math.max(0, Math.min(1, deformation));
        const releaseWeight = Math.max(0, -deformation);
        const strength = (0.95 + (1.14 - 0.95) * snap.value) + 0.62 * pressWeight;
        const pinch = (7.7 + (7.35 - 7.7) * snap.value) - 0.85 * pressWeight;
        const aberration = 0.10 + (0.13 - 0.10) * Math.max(snap.value, pressWeight);
        const zoom = 1 + 0.055 * snap.value + 0.025 * pressWeight;
        const wobble = 0.12 + 0.05 * snap.value + 0.06 * pressWeight + 0.18 * releaseWeight;

        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.useProgram(program);
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.uniform1i(uniforms.texture, 0);
        gl.uniform2f(uniforms.resolution, canvas.width, canvas.height);
        gl.uniform2f(uniforms.lensCenter, (x.value - roiLeft) * dpr, (y.value - roiTop) * dpr);
        gl.uniform2f(uniforms.lensSize, width.value * dpr * (1 + 0.025 * deformation), height.value * dpr * (1 - 0.085 * deformation));
        gl.uniform1f(uniforms.strength, strength);
        gl.uniform1f(uniforms.pinch, pinch);
        gl.uniform1f(uniforms.aberration, aberration);
        gl.uniform1f(uniforms.zoom, zoom);
        gl.uniform1f(uniforms.wobble, wobble);
        gl.uniform1f(uniforms.time, now / 1000);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
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

    const wake = () => ensureFrame();
    const handlePointerMove = (event: PointerEvent) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      pointerInside = true;
      snapDirty = true;
      wake();
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
      pressed = false;
      pressure.target = 0;
      activeTarget = null;
      snap.target = 0;
      snapDirty = true;
      wake();
    };
    const handlePointerEnter = () => { pointerInside = true; snapDirty = true; wake(); };
    const handleScroll = () => { roiLockedTarget = null; rasterDirty = true; snapDirty = true; wake(); };
    // Editing changes input.value without mutating DOM text or attributes.
    const handleInput = () => { rasterDirty = true; wake(); };
    const handleResize = () => {
      roiLeft = Number.NaN;
      roiTop = Number.NaN;
      roiLockedTarget = null;
      rasterDirty = true;
      snapDirty = true;
      wake();
    };

    const observer = new MutationObserver(() => {
      refreshMagneticTargets();
      rasterDirty = true;
      snapDirty = true;
      wake();
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["type", "value", "placeholder"] });
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
    document.documentElement.classList.add("powerbid-liquid-cursor-active");

    ensureFrame();

    return () => {
      window.cancelAnimationFrame(raf);
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
      document.documentElement.classList.remove("powerbid-liquid-cursor-active");
      for (const element of magneticTargets) element.style.removeProperty("translate");
      magneticStates.clear();
      gl.deleteTexture(texture);
      gl.deleteBuffer(position);
      gl.deleteBuffer(uv);
      gl.deleteProgram(program);
    };
  }, []);

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
