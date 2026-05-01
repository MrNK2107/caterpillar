import React, { useRef, useEffect, useCallback } from 'react';
import { useSimulationStore } from '@/simulation/store';
import { ZONE_COLORS, ZONE_BORDER_COLORS, YARD_POLYGON, DEFAULT_CONFIG, ENTRY_POINT } from '@/simulation/config';
// Removed particles

const Canvas2D: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { 
    grid, zones, trucks, blockedCells, showHeatmap, tick, piles,
    isDrawing, polygonVertices, settingEntryPoint, entryPoint, yardPolygon,
    addPolygonVertex, setEntryPoint
  } = useSimulationStore();

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawing && !settingEntryPoint) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);
    
    if (isDrawing) {
      addPolygonVertex({ x, y });
    } else if (settingEntryPoint) {
      setEntryPoint({ x, y });
      // Implicitly initialize the yard when the entry point is set
      useSimulationStore.getState().submitCustomYard();
    }
  }, [isDrawing, settingEntryPoint, addPolygonVertex, setEntryPoint]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = '#F9FAFB';
    ctx.fillRect(0, 0, W, H);

    // Yard polygon
    ctx.beginPath();
    const poly = yardPolygon.length > 0 ? yardPolygon : (isDrawing && polygonVertices.length > 0 ? polygonVertices : YARD_POLYGON);
    
    if (poly.length > 0) {
      ctx.moveTo(poly[0].x, poly[0].y);
      for (let i = 1; i < poly.length; i++) {
        ctx.lineTo(poly[i].x, poly[i].y);
      }
      if (yardPolygon.length > 0 || !isDrawing) ctx.closePath();
    }
    ctx.closePath();
    ctx.fillStyle = '#FFFFFF';
    ctx.fill();
    ctx.strokeStyle = '#D1D5DB';
    ctx.lineWidth = 2;
    ctx.stroke();

    
    // Draw polygon vertices if drawing
    if (isDrawing) {
      for (const p of polygonVertices) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#EF4444';
        ctx.fill();
        ctx.stroke();
      }
    }

    if (grid.length === 0 && !isDrawing && !settingEntryPoint) return;

    const cellW = (DEFAULT_CONFIG.yardWidth - DEFAULT_CONFIG.yardPadding * 2) / DEFAULT_CONFIG.gridCols;
    const cellH = (DEFAULT_CONFIG.yardHeight - DEFAULT_CONFIG.yardPadding * 2) / DEFAULT_CONFIG.gridRows;

    // Zone backgrounds and grids removed per requirements

    // Peak Points drawing removed per user request

    // Draw continuous dirt piles seamlessly merging together
    for (const pile of piles) {
      if (!pile) continue;
      
      ctx.save();
      ctx.beginPath();
      ctx.fillStyle = 'rgba(139, 69, 19, 0.6)'; // SaddleBrown
      ctx.arc(pile.x, pile.y, pile.radius, 0, Math.PI * 2);
      ctx.fill();
      
      ctx.beginPath();
      ctx.fillStyle = 'rgba(160, 82, 45, 0.9)'; // Sienna peak
      ctx.arc(pile.x, pile.y, pile.radius * 0.65, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // Debug: draw blocked reservation cells (red)
    for (const cell of blockedCells) {
      ctx.beginPath();
      ctx.fillStyle = 'rgba(239, 68, 68, 0.5)';
      ctx.arc(cell.x, cell.y, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Debug: draw planned paths (blue)
    for (const truck of trucks) {
      if (truck.path && truck.path.length >= 2) {
        ctx.beginPath();
        ctx.moveTo(truck.path[0].x, truck.path[0].y);
        for (let i = 1; i < truck.path.length; i++) {
          ctx.lineTo(truck.path[i].x, truck.path[i].y);
        }
        ctx.strokeStyle = 'rgba(37, 99, 235, 0.9)';
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Debug: draw truck targets (green)
    for (const truck of trucks) {
      const hasTarget = Number.isFinite(truck.targetX) && Number.isFinite(truck.targetY);
      if (hasTarget && (truck.state === 'moving_to_dump' || truck.state === 'requesting_dump')) {
        ctx.beginPath();
        ctx.fillStyle = 'rgba(34, 197, 94, 0.85)';
        ctx.arc(truck.targetX, truck.targetY, 5, 0, Math.PI * 2);
        ctx.fill();

        ctx.beginPath();
        ctx.strokeStyle = 'rgba(22, 163, 74, 0.95)';
        ctx.lineWidth = 2;
        ctx.arc(truck.targetX, truck.targetY, 8, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    // Draw trucks with enhanced physics visuals
    for (const truck of trucks) {
      const tx = truck.x;
      const ty = truck.y;
      
      const width = Math.max(8, Math.min(14, truck.model.width_m * 1.25));
      const length = Math.max(14, Math.min(28, truck.model.length_m * 1.45));

      ctx.save();
      ctx.translate(tx, ty);
      // truck.angle is absolute based on atan2 where 0 is right. We draw truck facing right.
      ctx.rotate(truck.angle);

      // Shadow
      ctx.fillStyle = 'rgba(0,0,0,0.15)';
      ctx.beginPath();
      ctx.roundRect(-length / 2 + 2, -width / 2 + 2, length, width, 2);
      ctx.fill();

      // Bed (rear part)
      const bedLength = length * 0.7;
      const cabLength = length * 0.3;
      
      ctx.fillStyle = truck.state === 'dumping' ? '#10B981' : truck.color;
      ctx.beginPath();
      ctx.roundRect(-length / 2, -width / 2, bedLength, width, 1);
      ctx.fill();
      ctx.strokeStyle = '#1F2937';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Cab (front part)
      ctx.fillStyle = '#E5E7EB'; // White/gray cab
      ctx.beginPath();
      ctx.roundRect(-length / 2 + bedLength, -width / 2 + 1, cabLength, width - 2, 2);
      ctx.fill();
      ctx.stroke();

      // Dump indicator
      if (truck.state === 'dumping') {
        const progress = 1 - truck.dumpTimer / DEFAULT_CONFIG.dumpDuration;
        ctx.fillStyle = '#059669';
        ctx.fillRect(-length / 2, -width / 2, bedLength * progress, width);
      }

      ctx.restore();

      // Status markers (drawn unrotated above truck)
      if (truck.state === 'waiting') {
        const pulse = 0.5 + Math.sin(tick * 0.4) * 0.5;
        ctx.fillStyle = `rgba(239, 68, 68, ${pulse})`;
        ctx.beginPath();
        ctx.arc(tx, ty - width - 6, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#FFF';
        ctx.font = 'bold 5px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('!', tx, ty - width - 4);
      }

      // Label
      ctx.fillStyle = '#1F2937';
      ctx.font = '600 7px JetBrains Mono';
      ctx.textAlign = 'center';
      ctx.fillText(truck.label, tx, ty + width + 8);

      // State label
      const stateLabels: Record<string, string> = {
        moving_to_dump: 'TRANSIT',
        dumping: 'DUMPING',
        returning: 'RETURN',
        waiting: 'WAIT',
        idle: 'IDLE',
      };
      ctx.fillStyle = '#6B7280';
      ctx.font = '500 5px JetBrains Mono';
      ctx.fillText(stateLabels[truck.state] || '', tx, ty + width + 14);
      ctx.textAlign = 'left';
    }

    // Removed dust and debris particles

    // Entry point indicator
    const currentEntryPoint = entryPoint || ENTRY_POINT;
    ctx.beginPath();
    ctx.arc(currentEntryPoint.x, currentEntryPoint.y, 8, 0, Math.PI * 2);
    ctx.fillStyle = 'hsla(48, 96%, 53%, 0.3)';
    ctx.fill();
    ctx.strokeStyle = '#FACC15';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = '#1F2937';
    ctx.font = '600 7px JetBrains Mono';
    ctx.textAlign = 'center';
    ctx.fillText('ENTRY', currentEntryPoint.x, currentEntryPoint.y + 16);
    ctx.textAlign = 'left';
    
    // Drawing UI Text Overlays
    if (isDrawing) {
      ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
      ctx.fillRect(W / 2 - 150, 10, 300, 30);
      ctx.fillStyle = '#FFF';
      ctx.font = '12px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('Click to add vertices to the custom yard polygon.', W / 2, 30);
    } else if (settingEntryPoint) {
      ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
      ctx.fillRect(W / 2 - 150, 10, 300, 30);
      ctx.fillStyle = '#FFF';
      ctx.font = '12px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('Click inside the yard to set the Entry Point.', W / 2, 30);
    }

  }, [grid, zones, trucks, blockedCells, showHeatmap, tick, piles, isDrawing, polygonVertices, settingEntryPoint, entryPoint, yardPolygon]);

  useEffect(() => {
    draw();
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      width={DEFAULT_CONFIG.yardWidth}
      height={DEFAULT_CONFIG.yardHeight}
      className={`w-full h-full ${isDrawing || settingEntryPoint ? 'cursor-crosshair' : ''}`}
      style={{ imageRendering: 'crisp-edges', touchAction: 'none' }}
      onPointerDown={handlePointerDown}
    />
  );
};

export default Canvas2D;
