import { intersects } from './targets';

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

export function rasterizePortal(
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
        // Numeric inputs may right-align their value. The old left-aligned
        // Canvas sample drew "220" on the opposite side of the input.
        const rtl = style.direction === "rtl";
        const align = style.textAlign;
        ctx.direction = rtl ? "rtl" : "ltr";
        ctx.textAlign = align === "center" ? "center"
          : align === "right" || (align === "start" && rtl) || (align === "end" && !rtl)
            ? "right" : "left";
        const textX = ctx.textAlign === "right"
          ? localX + rect.width - rightInset
          : ctx.textAlign === "center"
            ? localX + leftInset + clipWidth / 2
            : localX + leftInset;
        ctx.fillText(text, textX - el.scrollLeft, localY + rect.height / 2);
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
    // Sticky header is a positive z-index stacking layer. Native browser
    // paint order places it ABOVE the scrolling content, even though React
    // mounts it first. Repainting children in raw DOM order let offscreen
    // charts bleed through the header in the refracted ROI texture.
    const childNodes = Array.from(el.childNodes);
    if (el.classList.contains("app-main")) {
      childNodes.sort((a, b) =>
        Number(a instanceof HTMLElement && a.classList.contains("global-header")) -
        Number(b instanceof HTMLElement && b.classList.contains("global-header")));
    }
    for (const child of childNodes) {
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

