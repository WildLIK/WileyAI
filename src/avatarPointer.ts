/** Scale against the monitor, not a tiny avatar canvas: movement outside the
 * window must not immediately saturate at an unmoving hard-left/right pose. */
export function avatarPointer(
  point: { x: number; y: number; width: number; height: number },
  face: { x: number; y: number },
  canvas: { width: number; height: number },
) {
  const clamp = (value: number) => Math.max(-1, Math.min(1, value));
  return {
    x: clamp(
      (point.x - face.x) / Math.max(canvas.width * 0.65, point.width * 0.6, 1),
    ),
    y: clamp(
      (point.y - face.y) /
        Math.max(canvas.height * 0.65, point.height * 0.6, 1),
    ),
  };
}
