"use client";

/**
 * The canvas. SPEC.md §5, §11.
 *
 * `perfect-freehand` over a canvas, pointer events with pressure where available. Strokes go out
 * over the websocket as they finish, so every attached client sees them — that is M0's acceptance
 * test.
 *
 * The stroke-idle timer lives here rather than on the server because the server should not be
 * guessing about latency: the client knows exactly when the pen last lifted. On idle it snapshots
 * the affected region at 2x and posts it up for recognition (§5). Nothing is recognised locally.
 */

import { getStroke } from "perfect-freehand";
import { useCallback, useEffect, useRef, useState } from "react";

const IDLE_MS = 900;
const DENSITY = 2;

export type Point = { x: number; y: number; p: number; t: number };
export type Stroke = { id: string; points: Point[]; erase: boolean };

type Props = {
  onStroke: (stroke: Stroke) => void;
  /** PNG of the affected region at 2x, plus the region itself. */
  onIdle: (png: Blob, region: { x: number; y: number; w: number; h: number }) => void;
  /** Strokes from other clients in the room. */
  remote: Stroke[];
};

const OPTIONS = {
  size: 3.2,
  thinning: 0.55,
  smoothing: 0.6,
  streamline: 0.45,
  simulatePressure: true,
};

function toPath(points: Point[]): string {
  const outline = getStroke(
    points.map((p) => [p.x, p.y, p.p]),
    OPTIONS,
  );
  if (!outline.length) return "";
  const d = outline.reduce<string[]>((acc, [x0, y0], i, arr) => {
    const [x1, y1] = arr[(i + 1) % arr.length];
    acc.push(`${x0.toFixed(2)},${y0.toFixed(2)}`, `${((x0 + x1) / 2).toFixed(2)},${((y0 + y1) / 2).toFixed(2)}`);
    return acc;
  }, []);
  return `M${d[0]} Q${d.slice(1).join(" ")} Z`;
}

export default function Canvas({ onStroke, onIdle, remote }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [current, setCurrent] = useState<Point[]>([]);
  const [erasing, setErasing] = useState(false);
  const startedAt = useRef<number>(Date.now());
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dirty = useRef<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  const all = [...strokes, ...remote];

  /** Repaint. Kept simple: the canvas is small and the learner is writing, not animating. */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const ratio = window.devicePixelRatio || 1;
    const { width, height } = canvas.getBoundingClientRect();
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);

    ctx.fillStyle = "#1c1b19";
    for (const stroke of all) {
      if (stroke.erase) continue;
      const path = new Path2D(toPath(stroke.points));
      ctx.fill(path);
    }
    if (current.length) ctx.fill(new Path2D(toPath(current)));
  }, [strokes, current, remote, all]);

  const markDirty = useCallback((x: number, y: number) => {
    const box = dirty.current;
    dirty.current = box
      ? { x0: Math.min(box.x0, x), y0: Math.min(box.y0, y), x1: Math.max(box.x1, x), y1: Math.max(box.y1, y) }
      : { x0: x, y0: y, x1: x, y1: y };
  }, []);

  /** The stroke-idle boundary (§5). Snapshot the affected region only. */
  const scheduleIdle = useCallback(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => {
      const canvas = canvasRef.current;
      const box = dirty.current;
      if (!canvas || !box) return;

      const pad = 24;
      const region = {
        x: Math.max(0, box.x0 - pad),
        y: Math.max(0, box.y0 - pad),
        w: box.x1 - box.x0 + pad * 2,
        h: box.y1 - box.y0 + pad * 2,
      };

      const ratio = window.devicePixelRatio || 1;
      const off = document.createElement("canvas");
      off.width = region.w * DENSITY;
      off.height = region.h * DENSITY;
      const ctx = off.getContext("2d");
      if (!ctx) return;
      // White background: the recogniser sees paper, not transparency.
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, off.width, off.height);
      ctx.drawImage(
        canvas,
        region.x * ratio,
        region.y * ratio,
        region.w * ratio,
        region.h * ratio,
        0,
        0,
        off.width,
        off.height,
      );
      off.toBlob((blob) => {
        if (blob) onIdle(blob, region);
      }, "image/png");
      dirty.current = null;
    }, IDLE_MS);
  }, [onIdle]);

  const point = (e: React.PointerEvent<HTMLCanvasElement>): Point => {
    const rect = e.currentTarget.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      p: e.pressure > 0 ? e.pressure : 0.5,
      t: Date.now() - startedAt.current,
    };
  };

  return (
    <canvas
      ref={canvasRef}
      className="h-full w-full touch-none bg-paper"
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        setErasing(e.buttons === 32 || e.pointerType === "pen" && e.button === 5);
        const p = point(e);
        setCurrent([p]);
        markDirty(p.x, p.y);
        if (idleTimer.current) clearTimeout(idleTimer.current);
      }}
      onPointerMove={(e) => {
        if (!e.currentTarget.hasPointerCapture(e.pointerId) || !current.length) return;
        const p = point(e);
        setCurrent((prev) => [...prev, p]);
        markDirty(p.x, p.y);
      }}
      onPointerUp={() => {
        if (!current.length) return;
        const stroke: Stroke = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          points: current,
          erase: erasing,
        };
        setStrokes((prev) => [...prev, stroke]);
        setCurrent([]);
        onStroke(stroke);
        scheduleIdle();
      }}
    />
  );
}
