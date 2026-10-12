/** Map mouse/touch coordinates to the actual Chrome screenshot viewport.
 * The image uses object-fit:contain. The CSS box includes black letterboxing
 * that must not be counted when forwarding a school-page click.
 */
export function browserImagePoint(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
  naturalWidth: number,
  naturalHeight: number,
): {x: number; y: number} | null {
  if (![clientX, clientY, rect.left, rect.top, rect.width, rect.height,
    naturalWidth, naturalHeight].every(Number.isFinite) ||
      rect.width <= 0 || rect.height <= 0 || naturalWidth <= 0 || naturalHeight <= 0) {
    return null;
  }
  const scale = Math.min(rect.width / naturalWidth, rect.height / naturalHeight);
  const width = naturalWidth * scale;
  const height = naturalHeight * scale;
  const left = rect.left + (rect.width - width) / 2;
  const top = rect.top + (rect.height - height) / 2;
  if (clientX < left || clientY < top || clientX >= left + width || clientY >= top + height) {
    return null;
  }
  return {
    x: Math.min(naturalWidth - 1, Math.max(0, Math.round((clientX - left) / scale))),
    y: Math.min(naturalHeight - 1, Math.max(0, Math.round((clientY - top) / scale))),
  };
}
