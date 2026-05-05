import React, { useRef, useEffect, useCallback, useState } from 'react';
import { useSimulationStore } from '@/simulation/store';
import { DEFAULT_CONFIG, ENTRY_POINT } from '@/simulation/config';

const LOGICAL_W = DEFAULT_CONFIG.yardWidth;
const LOGICAL_H = DEFAULT_CONFIG.yardHeight;
const SNAP_RADIUS = 14;

const Canvas2D: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const {
    grid, trucks, blockedCells, tick, piles, assignmentDiagnostics,
    isDrawing, polygonVertices, settingEntryPoint, entryPoint, yardPolygon,
    addPolygonVertex, setEntryPoint, finishPolygon
  } = useSimulationStore();
  const [hoverPoint, setHoverPoint] = useState<{ x: number; y: number } | null>(null);

  const syncCanvasResolution = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const cssW = Math.max(1, rect.width || LOGICAL_W);
    const cssH = Math.max(1, rect.height || LOGICAL_H);
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));

    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform((cssW * dpr) / LOGICAL_W, 0, 0, (cssH * dpr) / LOGICAL_H, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
  }, []);

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawing && !settingEntryPoint) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * LOGICAL_W);
    const y = Math.round(((e.clientY - rect.top) / rect.height) * LOGICAL_H);

    if (isDrawing) {
      if (polygonVertices.length >= 3) {
        const first = polygonVertices[0];
        const d = Math.hypot(x - first.x, y - first.y);
        if (d <= SNAP_RADIUS) {
          finishPolygon();
          return;
        }
      }
      addPolygonVertex({ x, y });
    } else if (settingEntryPoint) {
      setEntryPoint({ x, y });
      useSimulationStore.getState().submitCustomYard();
    }
  }, [isDrawing, settingEntryPoint, polygonVertices, addPolygonVertex, setEntryPoint, finishPolygon]);

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawing) {
      setHoverPoint(null);
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * LOGICAL_W);
    const y = Math.round(((e.clientY - rect.top) / rect.height) * LOGICAL_H);
    setHoverPoint({ x, y });
  }, [isDrawing]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = LOGICAL_W;
    const H = LOGICAL_H;
    ctx.clearRect(0, 0, W, H);

    const bgGradient = ctx.createLinearGradient(0, 0, 0, H);
    bgGradient.addColorStop(0, '#091121');
    bgGradient.addColorStop(1, '#060b16');
    ctx.fillStyle = bgGradient;
    ctx.fillRect(0, 0, W, H);

    ctx.save();
    ctx.globalAlpha = 0.16;
    for (let y = 0; y < H; y += 30) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 0.7;
      ctx.stroke();
    }
    for (let x = 0; x < W; x += 30) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 0.7;
      ctx.stroke();
    }
    ctx.restore();

    const draftPolyline = isDrawing ? polygonVertices : [];
    const draftClosedPolygon = settingEntryPoint && yardPolygon.length >= 3 ? yardPolygon : [];
    const activeYardPolygon = !isDrawing && !settingEntryPoint && yardPolygon.length >= 3 ? yardPolygon : [];

    if (activeYardPolygon.length >= 3) {
      ctx.beginPath();
      ctx.moveTo(activeYardPolygon[0].x, activeYardPolygon[0].y);
      for (let i = 1; i < activeYardPolygon.length; i++) {
        ctx.lineTo(activeYardPolygon[i].x, activeYardPolygon[i].y);
      }
      ctx.closePath();

      const yardGradient = ctx.createLinearGradient(0, 30, 0, H - 30);
      yardGradient.addColorStop(0, '#1d2738');
      yardGradient.addColorStop(0.5, '#182335');
      yardGradient.addColorStop(1, '#131f31');
      ctx.fillStyle = yardGradient;
      ctx.fill();

      ctx.strokeStyle = '#7a8cab';
      ctx.lineWidth = 2.4;
      ctx.shadowColor = 'rgba(124, 153, 193, 0.24)';
      ctx.shadowBlur = 8;
      ctx.stroke();
      ctx.shadowBlur = 0;
    } else if (!isDrawing) {
      const yardGradient = ctx.createLinearGradient(0, 30, 0, H - 30);
      yardGradient.addColorStop(0, '#1d2738');
      yardGradient.addColorStop(0.5, '#182335');
      yardGradient.addColorStop(1, '#131f31');
      ctx.fillStyle = yardGradient;
      ctx.fillRect(0, 0, W, H);
    }

    if (draftClosedPolygon.length >= 3) {
      ctx.beginPath();
      ctx.moveTo(draftClosedPolygon[0].x, draftClosedPolygon[0].y);
      for (let i = 1; i < draftClosedPolygon.length; i++) {
        ctx.lineTo(draftClosedPolygon[i].x, draftClosedPolygon[i].y);
      }
      ctx.closePath();
      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 2;
      ctx.stroke();
    } else if (draftPolyline.length >= 2) {
      ctx.beginPath();
      ctx.moveTo(draftPolyline[0].x, draftPolyline[0].y);
      for (let i = 1; i < draftPolyline.length; i++) {
        ctx.lineTo(draftPolyline[i].x, draftPolyline[i].y);
      }
      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 2;
      ctx.stroke();

      if (hoverPoint) {
        ctx.beginPath();
        const last = draftPolyline[draftPolyline.length - 1];
        ctx.moveTo(last.x, last.y);
        ctx.lineTo(hoverPoint.x, hoverPoint.y);
        ctx.strokeStyle = 'rgba(250, 204, 21, 0.5)';
        ctx.lineWidth = 1.2;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    if (isDrawing) {
      for (const p of draftPolyline) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 4.4, 0, Math.PI * 2);
        ctx.fillStyle = '#facc15';
        ctx.fill();
        ctx.strokeStyle = '#0f172a';
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }

      if (draftPolyline.length >= 3 && hoverPoint) {
        const first = draftPolyline[0];
        const d = Math.hypot(hoverPoint.x - first.x, hoverPoint.y - first.y);
        if (d <= SNAP_RADIUS) {
          ctx.beginPath();
          ctx.arc(first.x, first.y, 8, 0, Math.PI * 2);
          ctx.strokeStyle = 'rgba(250, 204, 21, 0.9)';
          ctx.lineWidth = 2;
          ctx.stroke();

          ctx.beginPath();
          const last = draftPolyline[draftPolyline.length - 1];
          ctx.moveTo(last.x, last.y);
          ctx.lineTo(first.x, first.y);
          ctx.strokeStyle = 'rgba(250, 204, 21, 0.8)';
          ctx.lineWidth = 1.6;
          ctx.setLineDash([3, 3]);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    }

    if (grid.length === 0 && (isDrawing || settingEntryPoint || activeYardPolygon.length === 0)) {
      return;
    }

    for (const pile of piles) {
      if (!pile) continue;
      const pileGradient = ctx.createRadialGradient(pile.x, pile.y, pile.radius * 0.1, pile.x, pile.y, pile.radius);
      pileGradient.addColorStop(0, 'rgba(255, 246, 182, 0.85)');
      pileGradient.addColorStop(0.56, 'rgba(250, 204, 21, 0.58)');
      pileGradient.addColorStop(1, 'rgba(194, 106, 10, 0.16)');

      ctx.beginPath();
      ctx.fillStyle = pileGradient;
      ctx.arc(pile.x, pile.y, pile.radius, 0, Math.PI * 2);
      ctx.fill();
    }

    for (const cell of blockedCells) {
      ctx.beginPath();
      ctx.fillStyle = 'rgba(239, 68, 68, 0.72)';
      ctx.arc(cell.x, cell.y, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    for (const truck of trucks) {
      if (truck.path && truck.path.length >= 2 && (truck.state === 'moving_to_dump' || truck.state === 'returning')) {
        ctx.beginPath();
        ctx.moveTo(truck.path[0].x, truck.path[0].y);
        for (let i = 1; i < truck.path.length; i++) {
          ctx.lineTo(truck.path[i].x, truck.path[i].y);
        }
        ctx.strokeStyle = 'rgba(96, 165, 250, 0.75)';
        ctx.lineWidth = 1.2;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    for (const truck of trucks) {
      const diag = assignmentDiagnostics[String(truck.id)] as any;
      const trace = diag?.assignment_trace;
      const hasRealAssignment = Boolean(trace?.selected_xy);
      const hasTarget = Number.isFinite(truck.targetX) && Number.isFinite(truck.targetY);
      if (hasTarget && hasRealAssignment && truck.state === 'moving_to_dump') {
        ctx.beginPath();
        ctx.fillStyle = 'rgba(16, 185, 129, 0.9)';
        ctx.arc(truck.targetX, truck.targetY, 4.4, 0, Math.PI * 2);
        ctx.fill();

        ctx.beginPath();
        ctx.strokeStyle = 'rgba(110, 231, 183, 0.95)';
        ctx.lineWidth = 1.1;
        ctx.arc(truck.targetX, truck.targetY, 7.4, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    for (const truck of trucks) {
      const tx = truck.x;
      const ty = truck.y;

      const width = Math.max(9, Math.min(15, truck.model.width_m * 1.2));
      const length = Math.max(16, Math.min(30, truck.model.length_m * 1.42));
      const bedLength = length * 0.64;
      const cabLength = length * 0.26;
      const wheelRadius = Math.max(1.8, width * 0.18);
      const wheelOffsetX = length * 0.28;
      const wheelOffsetY = width * 0.54;

      ctx.save();
      ctx.translate(tx, ty);
      ctx.rotate(truck.angle);

      ctx.fillStyle = 'rgba(2, 6, 23, 0.44)';
      ctx.beginPath();
      ctx.roundRect(-length / 2 + 2, -width / 2 + 2, length, width, 2);
      ctx.fill();

      ctx.fillStyle = '#1f2937';
      ctx.beginPath();
      ctx.roundRect(-length / 2, -width / 2, length * 0.9, width, 2.4);
      ctx.fill();

      ctx.fillStyle = truck.state === 'dumping' ? '#10B981' : truck.color;
      ctx.beginPath();
      ctx.roundRect(-length / 2 + 1, -width / 2 + 1, bedLength, width - 2, 1.8);
      ctx.fill();
      ctx.strokeStyle = '#0b1220';
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.fillStyle = '#cbd5e1';
      ctx.beginPath();
      ctx.roundRect(-length / 2 + bedLength, -width / 2 + 1.4, cabLength, width - 2.8, 2.2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#93c5fd';
      ctx.fillRect(-length / 2 + bedLength + 2, -width * 0.3, cabLength * 0.45, width * 0.24);

      const wheels = [
        [-wheelOffsetX, -wheelOffsetY],
        [wheelOffsetX, -wheelOffsetY],
        [-wheelOffsetX, wheelOffsetY],
        [wheelOffsetX, wheelOffsetY],
      ];
      for (const [wx, wy] of wheels) {
        ctx.beginPath();
        ctx.arc(wx, wy, wheelRadius, 0, Math.PI * 2);
        ctx.fillStyle = '#0f172a';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(wx, wy, wheelRadius * 0.55, 0, Math.PI * 2);
        ctx.fillStyle = '#475569';
        ctx.fill();
      }

      if (truck.state === 'dumping') {
        const progress = 1 - truck.dumpTimer / DEFAULT_CONFIG.dumpDuration;
        ctx.fillStyle = '#22c55e';
        ctx.fillRect(-length / 2 + 1.5, -width / 2 + 1.5, (bedLength - 2) * progress, width - 3);
      }

      ctx.restore();

      const badgeY = ty + width + 8;
      ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
      ctx.fillRect(tx - 23, badgeY - 8, 46, 10);
      ctx.strokeStyle = 'rgba(250, 204, 21, 0.65)';
      ctx.lineWidth = 0.8;
      ctx.strokeRect(tx - 23, badgeY - 8, 46, 10);
      ctx.fillStyle = '#f8fafc';
      ctx.font = '700 7px JetBrains Mono';
      ctx.textAlign = 'center';
      ctx.fillText(`T${truck.id + 1}`, tx, badgeY - 1);

      const stateLabels: Record<string, string> = {
        moving_to_dump: 'APPROACH',
        dumping: 'DUMPING',
        returning: 'RETURN',
        waiting: 'WAIT',
        idle: 'IDLE',
      };
      ctx.fillStyle = '#94a3b8';
      ctx.font = '600 6px JetBrains Mono';
      ctx.fillText(stateLabels[truck.state] || '', tx, badgeY + 8);
      ctx.textAlign = 'left';

      if (truck.state === 'waiting') {
        const pulse = 0.5 + Math.sin(tick * 0.4) * 0.5;
        ctx.fillStyle = `rgba(239, 68, 68, ${pulse})`;
        ctx.beginPath();
        ctx.arc(tx, ty - width - 7, 4, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    const currentEntryPoint = entryPoint || ENTRY_POINT;
    ctx.beginPath();
    ctx.arc(currentEntryPoint.x, currentEntryPoint.y, 8, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(250, 204, 21, 0.28)';
    ctx.fill();
    ctx.strokeStyle = '#facc15';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = '#f8fafc';
    ctx.font = '600 7px JetBrains Mono';
    ctx.textAlign = 'center';
    ctx.fillText('ENTRY', currentEntryPoint.x, currentEntryPoint.y + 16);
    ctx.textAlign = 'left';

  }, [grid, trucks, blockedCells, tick, piles, assignmentDiagnostics, isDrawing, polygonVertices, settingEntryPoint, entryPoint, yardPolygon, hoverPoint]);

  useEffect(() => {
    syncCanvasResolution();
    draw();
  }, [syncCanvasResolution, draw]);

  useEffect(() => {
    const onResize = () => {
      syncCanvasResolution();
      draw();
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [syncCanvasResolution, draw]);

  return (
    <canvas
      ref={canvasRef}
      width={LOGICAL_W}
      height={LOGICAL_H}
      className={`h-full w-full ${isDrawing || settingEntryPoint ? 'cursor-crosshair' : ''}`}
      style={{ touchAction: 'none' }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
    />
  );
};

export default Canvas2D;
