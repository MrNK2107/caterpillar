import { create } from 'zustand';
import { GridCell, Zone, Truck, SimMetrics, Point, TruckState, Pile, FleetConfig, ScenarioConfig } from './types';
import { DEFAULT_CONFIG, DEFAULT_FLEET, DEFAULT_SCENARIO, ZONE_COLORS, ZONE_BORDER_COLORS, TRUCK_COLORS, ENTRY_POINT, CAT_TRUCK_MODELS, CAT_MODEL_GROUPS } from './config';
import { playDumpSound } from './sounds';
// Removed particles

interface SimulationState {
  // State
  running: boolean;
  speed: number;
  viewMode: '2d' | '3d';
  showHeatmap: boolean;
  tick: number;

  // Custom Yard Drawing
  isDrawing: boolean;
  polygonVertices: Point[];
  settingEntryPoint: boolean;
  entryPoint: Point | null;
  yardPolygon: Point[];

  // Data
  grid: GridCell[][];
  zones: Zone[];
  trucks: Truck[];
  blockedCells: Point[];
  piles: Pile[];
  fleetConfig: FleetConfig;
  scenario: ScenarioConfig;
  metrics: SimMetrics;
  // Removed particles
  currentZoneIndex: number; // which zone is being filled

  // Actions
  init: () => Promise<void>;
  start: () => void;
  pause: () => void;
  reset: () => Promise<void>;
  setSpeed: (s: number) => void;
  setViewMode: (m: '2d' | '3d') => void;
  toggleHeatmap: () => void;
  setFleetCounts: (config: FleetConfig) => Promise<void>;
  step: () => void;
  
  // Custom Yard Actions
  addPolygonVertex: (p: Point) => void;
  finishPolygon: () => void;
  setEntryPointMode: () => void;
  setEntryPoint: (p: Point) => void;
  resetDrawing: () => void;
  startDrawingMode: () => void;
  submitCustomYard: () => Promise<void>;
}

const API_BASE = 'http://localhost:8000/api';
const DEMO_LOOP_MODE = false;
const DEMO_MIN_SPACING = 26;
const DEADLOCK_WAIT_STEPS = 20;

function getTruckStagingOffset(index: number, total: number) {
  return (index - (Math.max(total, 1) - 1) / 2) * 18;
}

function getTruckModel(modelName: string) {
  return CAT_TRUCK_MODELS[modelName as keyof typeof CAT_TRUCK_MODELS];
}

function getDumpRadiusForTruck(truck: Truck) {
  const halfLength = truck.model.pile_length_m / 2;
  const halfWidth = truck.model.pile_width_m / 2;
  return Math.max(Math.hypot(halfLength, halfWidth), 4);
}

function getPilePeakHeight(truck: Truck) {
  return Math.max(0.25, Math.sqrt(truck.model.pile_length_m * truck.model.pile_width_m) * 0.18);
}

function applyDumpToGrid(grid: GridCell[][], center: Point, truck: Truck, scenario: ScenarioConfig) {
  if (grid.length === 0 || grid[0].length === 0) return;

  const spreadFactor = scenario.material.spreadFactor;
  const rainFactor = 1 + Math.max(0, Math.min(1, scenario.weather.rainIntensity)) * 0.2;
  const windBias = scenario.weather.windSpeed * 0.03;
  const windDirection = (scenario.weather.windDirectionDeg * Math.PI) / 180;
  const windX = Math.cos(windDirection) * windBias;
  const windY = Math.sin(windDirection) * windBias;

  const peakHeight = getPilePeakHeight(truck) / Math.max(0.7, spreadFactor * rainFactor);
  const semiMajor = Math.max(DEFAULT_CONFIG.cellSize / 2, (truck.model.pile_length_m / 2) * spreadFactor * rainFactor);
  const semiMinor = Math.max(DEFAULT_CONFIG.cellSize / 2, (truck.model.pile_width_m / 2) * spreadFactor * rainFactor);

  for (const row of grid) {
    for (const cell of row) {
      if (cell.zoneId === -1) continue;

      const shiftedX = cell.x - center.x - windX;
      const shiftedY = cell.y - center.y - windY;
      const normX = shiftedX / semiMajor;
      const normY = shiftedY / semiMinor;
      const normalizedDistance = normX * normX + normY * normY;
      if (normalizedDistance > 1) continue;

      const radialFactor = Math.sqrt(normalizedDistance);
      const heightDelta = peakHeight * Math.max(0, 1 - radialFactor) ** 1.35;
      if (heightDelta <= 0) continue;

      cell.height += heightDelta;
      if (cell.height >= peakHeight * 0.85) {
        cell.filled = true;
      }
    }
  }
}

// registerZoneWithBackend removed as it is legacy

async function registerTruckWithBackend(truck: Truck) {
  try {
    await fetch(`${API_BASE}/trucks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        truck_id: truck.id.toString(),
        model: truck.model,
        current_position: { x: truck.x, y: truck.y },
        state: 'IDLE'
      })
    });
  } catch (e) { console.error('Error registering truck', e); }
}

let isRequestingLock = new Set<number>();
let backendStepIntervalId: ReturnType<typeof globalThis.setInterval> | null = null;
let backendStepInFlight = false;

function mapBackendTruckState(rawState: string | undefined, rawAgentState: string | undefined): TruckState {
  const agentState = (rawAgentState || '').toUpperCase();
  if (agentState === 'REQUESTING_DUMP') return 'requesting_dump';
  if (agentState === 'MOVING_TO_DUMP') return 'moving_to_dump';
  if (agentState === 'DUMPING') return 'dumping';
  if (agentState === 'RETURNING') return 'returning';
  if (agentState === 'IDLE') return 'idle';

  const state = (rawState || '').toUpperCase();
  if (state === 'WAITING') return 'waiting';
  if (state === 'EN_ROUTE') return 'moving_to_dump';
  if (state === 'DUMPING') return 'dumping';
  if (state === 'IDLE') return 'idle';
  return 'idle';
}

function normalizeMetricsFromBackend(backendMetrics: any, current: SimMetrics): SimMetrics {
  if (!backendMetrics || typeof backendMetrics !== 'object') {
    return {
      ...current,
      timeSteps: current.timeSteps + 1,
      spacingHistory: [...(current.spacingHistory ?? []), current.avgSpacing ?? 1.0].slice(-60),
    };
  }

  const summary = backendMetrics.summary ?? {};
  const comparison = backendMetrics.comparison?.new_system ?? {};
  const packingDensityPct = Math.max(0, Math.min(100, Number(comparison.packing_density ?? 0) * 100));
  const avgSpacing = Number(comparison.average_spacing_m ?? current.avgSpacing ?? 0);

  return {
    ...current,
    totalDumps: Number(summary.total_dumps ?? current.totalDumps ?? 0),
    avgSpacing,
    packingDensity: Math.round(packingDensityPct * 10) / 10,
    densityHistory: [...current.densityHistory, Math.round(packingDensityPct * 10) / 10].slice(-60),
    spacingHistory: [...(current.spacingHistory ?? []), avgSpacing].slice(-60),
    timeSteps: current.timeSteps + 1,
  };
}

async function runBackendStepTick() {
  if (backendStepInFlight) return;
  backendStepInFlight = true;
  try {
    const res = await fetch('http://127.0.0.1:8000/api/step', { method: 'POST' });
    if (!res.ok) {
      throw new Error(`Backend step failed: ${res.status}`);
    }

    const data = await res.json();
    useSimulationStore.setState((state) => {
      const backendTrucks = (data?.trucks ?? {}) as Record<string, any>;
      const blockedCellsRaw = Array.isArray(data?.blocked_cells) ? data.blocked_cells : [];
      const newTrucks = state.trucks.map((truck) => {
        const backendTruck = backendTrucks[truck.id.toString()];
        if (!backendTruck) {
          return truck;
        }

        const next = { ...truck };
        const position = backendTruck.position;
        const assignment = backendTruck.assignment;

        if (position && typeof position.x === 'number' && typeof position.y === 'number') {
          next.x = position.x;
          next.y = position.y;
        }

        if (assignment && typeof assignment.x === 'number' && typeof assignment.y === 'number') {
          next.targetX = assignment.x;
          next.targetY = assignment.y;
        } else {
          next.targetX = next.x;
          next.targetY = next.y;
          next.targetCell = null;
        }

        next.state = mapBackendTruckState(backendTruck.state, backendTruck.agent_state);
        if (Array.isArray(backendTruck.planned_path) && backendTruck.planned_path.length > 0) {
          next.path = backendTruck.planned_path
            .filter((point: any) => typeof point?.x === 'number' && typeof point?.y === 'number')
            .map((point: any) => ({ x: point.x, y: point.y }));
        } else {
          next.path = null;
        }
        next.pathIndex = 0;
        next.waitTimer = 0;
        if (next.state !== 'waiting') {
          next.waitingSteps = 0;
          next.deadlocked = false;
        }

        return next;
      });

      return {
        trucks: newTrucks,
        blockedCells: blockedCellsRaw
          .filter((cell: any) => typeof cell?.x === 'number' && typeof cell?.y === 'number')
          .map((cell: any) => ({ x: cell.x, y: cell.y })),
        metrics: normalizeMetricsFromBackend(data?.metrics, state.metrics),
        tick: state.tick + 1,
      };
    });
  } catch (e) {
    console.error('Error stepping backend simulation', e);
  } finally {
    backendStepInFlight = false;
  }
}

function startBackendLoop() {
  if (backendStepIntervalId !== null) return;
  backendStepIntervalId = globalThis.setInterval(() => {
    void runBackendStepTick();
  }, 200);
  void runBackendStepTick();
}

function stopBackendLoop() {
  if (backendStepIntervalId !== null) {
    globalThis.clearInterval(backendStepIntervalId);
    backendStepIntervalId = null;
  }
}

async function requestDump(truckId: number, currentX: number, currentY: number, zoneId: number) {
  if (isRequestingLock.has(truckId)) return;
  isRequestingLock.add(truckId);
  const zoneName = `zone_${zoneId}`;
  try {
    const res = await fetch(`${API_BASE}/assign_dump`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        truck_id: truckId.toString(),
        zone_name: zoneName,
        current_position: { x: currentX, y: currentY }
      })
    });
    
    if (!res.ok) {
      // Backend rejected (zone full or error) -> Wait and retry
      useSimulationStore.setState(state => {
        const newTrucks = [...state.trucks];
        const t = newTrucks.find(t => t.id === truckId);
        if (t) {
          t.state = 'waiting';
          t.waitTimer = 60; // Wait 1 second (at 60fps) before trying again
          t.waitingSteps = 0;
          t.deadlocked = false;
        }
        return { trucks: newTrucks };
      });
      isRequestingLock.delete(truckId);
      return;
    }

    const data = await res.json();
    if (data?.status === 'no_assignment') {
      useSimulationStore.setState(state => {
        const newTrucks = [...state.trucks];
        const t = newTrucks.find(t => t.id === truckId);
        if (t) {
          t.state = 'waiting';
          t.waitTimer = 60;
          t.waitingSteps = 0;
          t.deadlocked = false;
        }
        return { trucks: newTrucks };
      });
      isRequestingLock.delete(truckId);
      return;
    }

    const target = data.target;
    const path = data.path;
    useSimulationStore.setState(state => {
      const newTrucks = [...state.trucks];
      const t = newTrucks.find(t => t.id === truckId);
      if (t) {
        t.path = path;
        t.pathIndex = 0;
        t.targetX = target.x;
        t.targetY = target.y;
        
        // Find nearest cell in grid to mark it visually
        let minDist = Infinity;
        let closestCell = state.grid[0][0];
        for (let r=0; r<state.grid.length; r++) {
          for(let c=0; c<state.grid[r].length; c++) {
            const cell = state.grid[r][c];
            const d = Math.sqrt((cell.x - target.x)**2 + (cell.y - target.y)**2);
            if (d < minDist) { minDist = d; closestCell = cell; }
          }
        }
        t.targetCell = { row: closestCell.row, col: closestCell.col };
        t.state = 'moving_to_dump';
        t.waitingSteps = 0;
        t.deadlocked = false;
      }
      return { trucks: newTrucks };
    });
  } catch (e) {
      console.error('Error requesting dump from API', e);
      useSimulationStore.setState(state => {
        const newTrucks = [...state.trucks];
        const t = newTrucks.find(t => t.id === truckId);
        if (t) { t.state = 'waiting'; t.waitTimer = 60; t.waitingSteps = 0; t.deadlocked = false; }
        return { trucks: newTrucks };
      });
  }
  isRequestingLock.delete(truckId);
}

async function finishDumpAndReturn(truckId: number, zoneId: number, currentX: number, currentY: number, ep: Point) {
  if (isRequestingLock.has(truckId)) return;
  isRequestingLock.add(truckId);
  try {
    await fetch(`${API_BASE}/complete_dump?truck_id=${truckId}&zone_name=zone_${zoneId}`, {
      method: 'POST'
    });
    
    const zoneName = `zone_${zoneId}`;
    const res = await fetch(`${API_BASE}/return_route?zone_name=${zoneName}&entry_x=${ep.x}&entry_y=${ep.y}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        truck_id: truckId.toString(),
        current_position: { x: currentX, y: currentY }
      })
    });
    
    if (res.ok) {
       const route = await res.json();
       useSimulationStore.setState(state => {
         const newTrucks = [...state.trucks];
         const t = newTrucks.find(trk => trk.id === truckId);
         if (t) {
            // Valid A* Array path parsed back! Avoid sliding into the global skip behavior
            if (route.length > 0) {
               t.path = route;
            } else {
               t.path = [ep];
            }
            t.pathIndex = 0;
            t.state = 'returning';
         }
         return { trucks: newTrucks };
       });
    } else {
       useSimulationStore.setState(state => {
         const newTrucks = [...state.trucks];
         const t = newTrucks.find(trk => trk.id === truckId);
         if (t) { t.path = [ep]; t.pathIndex = 0; t.state = 'returning'; }
         return { trucks: newTrucks };
       });
    }
  } catch (e) {
      console.error('Error in finishDumpAndReturn', e);
      useSimulationStore.setState(state => {
         const newTrucks = [...state.trucks];
         const t = newTrucks.find(trk => trk.id === truckId);
         if (t) { t.path = [ep]; t.pathIndex = 0; t.state = 'returning'; }
         return { trucks: newTrucks };
       });
  }
  isRequestingLock.delete(truckId);
}

async function releaseReservation(truckId: number) {
  try {
    await fetch(`${API_BASE}/release_reservation?truck_id=${truckId}`, {
      method: 'POST'
    });
  } catch (e) {
    console.error('Error releasing reservation', e);
  }
}

function deadlockPriority(truck: Truck): number {
  const payload = truck.model.payload_tonnes;
  const distanceToDump = Math.hypot(truck.targetX - truck.x, truck.targetY - truck.y);
  return payload / (distanceToDump + 1);
}

function createGrid(): GridCell[][] {
  const { gridRows, gridCols, yardPadding } = DEFAULT_CONFIG;
  const cellW = (DEFAULT_CONFIG.yardWidth - yardPadding * 2) / gridCols;
  const cellH = (DEFAULT_CONFIG.yardHeight - yardPadding * 2) / gridRows;

  const grid: GridCell[][] = [];
  for (let r = 0; r < gridRows; r++) {
    const row: GridCell[] = [];
    for (let c = 0; c < gridCols; c++) {
      row.push({
        row: r,
        col: c,
        x: yardPadding + c * cellW + cellW / 2,
        y: yardPadding + r * cellH + cellH / 2,
        height: 0,
        filled: false,
        zoneId: -1,
      });
    }
    grid.push(row);
  }
  return grid;
}

function assignZones(grid: GridCell[][]): Zone[] {
  const { numZones, gridRows, gridCols } = DEFAULT_CONFIG;
  const zones: Zone[] = [];

  const zoneCols = Math.ceil(Math.sqrt(numZones));
  const zoneRows = Math.ceil(numZones / zoneCols);

  for (let z = 0; z < numZones; z++) {
    zones.push({
      id: z,
      center: { x: 0, y: 0 },
      color: ZONE_COLORS[z % ZONE_COLORS.length],
      cells: [],
      dumpCount: 0,
    });
  }

  for (let r = 0; r < gridRows; r++) {
    for (let c = 0; c < gridCols; c++) {
      const zr = Math.min(Math.floor(r / (gridRows / zoneRows)), zoneRows - 1);
      const zc = Math.min(Math.floor(c / (gridCols / zoneCols)), zoneCols - 1);
      const zoneId = Math.min(zr * zoneCols + zc, numZones - 1);
      grid[r][c].zoneId = zoneId;
      zones[zoneId].cells.push(grid[r][c]);
    }
  }

  for (const z of zones) {
    if (z.cells.length > 0) {
      z.center = {
        x: z.cells.reduce((s, c) => s + c.x, 0) / z.cells.length,
        y: z.cells.reduce((s, c) => s + c.y, 0) / z.cells.length,
      };
    }
  }

  return zones;
}

function createTrucks(zones: Zone[], ePoint: Point = ENTRY_POINT, fleetConfig: FleetConfig = DEFAULT_FLEET): Truck[] {
  const trucks: Truck[] = [];
  const truckModelNames: string[] = [
    ...Array.from({ length: Math.max(0, fleetConfig.large) }, (_, i) => CAT_MODEL_GROUPS.large[i % CAT_MODEL_GROUPS.large.length]),
    ...Array.from({ length: Math.max(0, fleetConfig.small) }, (_, i) => CAT_MODEL_GROUPS.small[i % CAT_MODEL_GROUPS.small.length]),
  ];
  const totalTrucks = truckModelNames.length;

  for (let i = 0; i < totalTrucks; i++) {
    const zoneId = zones.length > 0 ? i % zones.length : 0;
    const modelName = truckModelNames[i] ?? 'Cat 777G';
    const model = getTruckModel(modelName);
    const modelCode = modelName.replace(/[^0-9A-Za-z]/g, '').toUpperCase();
    trucks.push({
      id: i,
      label: `${modelCode}-${String(i + 1).padStart(2, '0')}`,
      modelName,
      model,
      x: ePoint.x,
      y: ePoint.y + getTruckStagingOffset(i, totalTrucks),
      angle: 0,
      vx: 0,
      vy: 0,
      targetX: ePoint.x,
      targetY: ePoint.y,
      speed: DEMO_LOOP_MODE ? DEFAULT_CONFIG.truckSpeed * 0.95 : DEFAULT_CONFIG.truckSpeed + (Math.random() - 0.5) * 0.5,
      state: 'idle',
      assignedZone: zoneId,
      dumpCount: 0,
      targetCell: null,
      path: null,
      pathIndex: 0,
      zoneName: `zone_${zones[zoneId]?.id ?? zoneId}`,
      waitTimer: 0,
      waitingSteps: 0,
      deadlocked: false,
      dumpTimer: 0,
      color: TRUCK_COLORS[i % TRUCK_COLORS.length],
    });
  }
  return trucks;
}

function isZoneComplete(zone: Zone, grid: GridCell[][]): boolean {
  return zone.cells.every(c => grid[c.row][c.col].filled || grid[c.row][c.col].height >= 5);
}

function pointInPolygon(point: Point, vs: Point[]): boolean {
  const x = point.x;
  const y = point.y;
  let inside = false;
  for (let i = 0, j = vs.length - 1; i < vs.length; j = i++) {
    const xi = vs[i].x, yi = vs[i].y;
    const xj = vs[j].x, yj = vs[j].y;
    const intersect = ((yi > y) !== (yj > y))
        && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function distance(a: Point, b: Point): number {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

function moveTowardDirect(truck: Truck, tx: number, ty: number, speed: number): boolean {
  const dx = tx - truck.x;
  const dy = ty - truck.y;
  const dist = Math.sqrt(dx * dx + dy * dy);

  if (dist <= Math.max(2, speed + 0.5)) {
    truck.x = tx;
    truck.y = ty;
    truck.angle = Math.atan2(dy, dx) || truck.angle;
    return true;
  }

  truck.angle = Math.atan2(dy, dx);
  const step = Math.min(speed, dist);
  truck.x += (dx / dist) * step;
  truck.y += (dy / dist) * step;
  return false;
}

function getDemoDumpRadius(truck: Truck): number {
  return getDumpRadiusForTruck(truck);
}

function isSpotAvailableForDemo(
  x: number,
  y: number,
  radius: number,
  piles: Pile[],
  trucks: Truck[],
  selfId: number,
): boolean {
  // Prevent reusing existing dump points.
  for (const p of piles) {
    const d = Math.hypot(p.x - x, p.y - y);
    if (d < (radius + p.radius) * 0.92) {
      return false;
    }
  }

  // Prevent assigning points already targeted by other trucks this cycle.
  for (const t of trucks) {
    if (t.id === selfId) continue;
    if (t.state === 'moving_to_dump' || t.state === 'dumping' || t.state === 'requesting_return') {
      const d = Math.hypot(t.targetX - x, t.targetY - y);
      if (d < Math.max(DEMO_MIN_SPACING, radius * 1.4)) {
        return false;
      }
    }
  }

  return true;
}

function getDemoDumpTarget(
  truck: Truck,
  zones: Zone[],
  piles: Pile[],
  trucks: Truck[],
  yardPoly: Point[],
): Point {
  const minX = DEFAULT_CONFIG.yardPadding + 20;
  const maxX = DEFAULT_CONFIG.yardWidth - DEFAULT_CONFIG.yardPadding - 20;
  const minY = DEFAULT_CONFIG.yardPadding + 24;
  const maxY = DEFAULT_CONFIG.yardHeight - DEFAULT_CONFIG.yardPadding - 24;

  const radius = getDemoDumpRadius(truck);
  const xStep = Math.max(10, Math.floor(radius * 1.15));
  const yStep = Math.max(10, Math.floor(radius * 1.1));

  const laneCount = Math.max(1, trucks.length);
  const laneStep = laneCount > 1 ? (maxY - minY) / (laneCount - 1) : 0;
  const laneY = minY + laneStep * truck.id;

  const activePoly = yardPoly.length >= 3
    ? yardPoly
    : [
        { x: DEFAULT_CONFIG.yardPadding, y: DEFAULT_CONFIG.yardPadding },
        { x: DEFAULT_CONFIG.yardWidth - DEFAULT_CONFIG.yardPadding, y: DEFAULT_CONFIG.yardPadding },
        { x: DEFAULT_CONFIG.yardWidth - DEFAULT_CONFIG.yardPadding, y: DEFAULT_CONFIG.yardHeight - DEFAULT_CONFIG.yardPadding },
        { x: DEFAULT_CONFIG.yardPadding, y: DEFAULT_CONFIG.yardHeight - DEFAULT_CONFIG.yardPadding },
      ];

  // Far-end-first candidate search: fill from the back wall toward entry.
  const yOffsets: number[] = [0];
  for (let k = 1; k <= 12; k++) {
    yOffsets.push(k * yStep, -k * yStep);
  }

  for (let x = maxX; x >= minX; x -= xStep) {
    for (const dy of yOffsets) {
      const y = laneY + dy;
      if (y < minY || y > maxY) continue;
      if (!pointInPolygon({ x, y }, activePoly)) continue;
      if (isSpotAvailableForDemo(x, y, radius, piles, trucks, truck.id)) {
        return { x, y };
      }
    }
  }

  // Last-resort fallback (still deterministic) if area is saturated.
  const fallbackX = Math.max(minX, maxX - (truck.dumpCount % 20) * xStep);
  const fallbackY = Math.max(minY, Math.min(maxY, laneY));

  return {
    x: fallbackX,
    y: fallbackY,
  };
}

function shouldYieldInDemo(truck: Truck, trucks: Truck[]): boolean {
  for (const other of trucks) {
    if (other.id === truck.id) continue;
    const dx = other.x - truck.x;
    const dy = other.y - truck.y;
    const d = Math.hypot(dx, dy);
    if (d < DEMO_MIN_SPACING && other.id < truck.id) {
      return true;
    }
  }
  return false;
}

function moveToward(truck: Truck, tx: number, ty: number, speed: number): boolean {
  const dx = tx - truck.x;
  const dy = ty - truck.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  
  if (dist < 2.0) {
    truck.x = tx;
    truck.y = ty;
    return true;
  }
  
  const targetAngle = Math.atan2(dy, dx);
  let angleDiff = targetAngle - truck.angle;
  while (angleDiff > Math.PI) angleDiff -= Math.PI * 2;
  while (angleDiff < -Math.PI) angleDiff += Math.PI * 2;
  
  const maxTurnRate = 0.2;
  truck.angle += Math.max(-maxTurnRate, Math.min(maxTurnRate, angleDiff));
  
  while (truck.angle > Math.PI * 2) truck.angle -= Math.PI * 2;
  while (truck.angle < 0) truck.angle += Math.PI * 2;

  let currentSpeed = speed;
  if (dist < 15) {
      // Very close: throttle drastically based on angle deviation to allow spinning into the waypoint facing it perfectly
      const severity = Math.min(Math.abs(angleDiff) / (Math.PI / 4), 1);
      currentSpeed = speed * (1 - severity * 0.95);
  } else {
      const severity = Math.min(Math.abs(angleDiff) / Math.PI, 1);
      currentSpeed = speed * (1 - severity * 0.6);
  }
  
  truck.x += Math.cos(truck.angle) * currentSpeed;
  truck.y += Math.sin(truck.angle) * currentSpeed;
  return false;
}

function avoidCollisions(truck: Truck, trucks: Truck[]): { stop: boolean } {
  for (const other of trucks) {
    if (other.id === truck.id) continue;
    
    // Ignore trucks that are fully parked and NOT physical obstacles
    // (We now treat 'idle' trucks as solid physical bodies so traffic queues correctly behind them!)
    
    const dx = other.x - truck.x;
    const dy = other.y - truck.y;
    // Hard physical distance check buffer
    const d = Math.sqrt(dx * dx + dy * dy);
    
    if (d < 30 && d > 0) {
      const angleToOther = Math.atan2(dy, dx);
      let angleDiff = angleToOther - truck.angle;
      while (angleDiff > Math.PI) angleDiff -= Math.PI * 2;
      while (angleDiff < -Math.PI) angleDiff += Math.PI * 2;
      
      // 60-degree Front Cone detection.
      if (Math.abs(angleDiff) < Math.PI / 3.0) {
         // Priority yielding to prevent mutual deadlocks
         if (other.state === 'dumping' || other.state === 'waiting' || other.state === 'idle' || other.id < truck.id) {
            truck.vx = 0;
            truck.vy = 0;
            return { stop: true };
         }
      }
    }
  }
  return { stop: false };
}

export const useSimulationStore = create<SimulationState>((set, get) => ({
  running: false,
  speed: 1,
  viewMode: '2d',
  showHeatmap: false,
  tick: 0,
  fleetConfig: DEFAULT_FLEET,
  scenario: DEFAULT_SCENARIO,
  grid: [],
  zones: [],
  trucks: [],
  blockedCells: [],
  piles: [],
  // Removed particles
  currentZoneIndex: 0,
  
  isDrawing: false,
  polygonVertices: [],
  settingEntryPoint: false,
  entryPoint: null,
  yardPolygon: [],
  metrics: {
    totalDumps: 0,
    missedDumps: 0,
    avgSpacing: 1.0,
    packingDensity: 0,
    densityHistory: [],
    spacingHistory: [],
    zoneDumps: [],
    timeSteps: 0,
    maxPeakDistance: 0,
    peakPoints: null,
  },

  init: async () => {
    stopBackendLoop();
    backendStepInFlight = false;
    isRequestingLock.clear();
    const state = get();
    let grid = createGrid();
    let zones: Zone[] = [];
    let trucks: Truck[] = [];
    
    let yardPoly = state.yardPolygon;
    let ep = state.entryPoint || ENTRY_POINT;
    const scenario = { ...state.scenario, dumpPolygon: state.yardPolygon.length > 0 ? state.yardPolygon : state.scenario.dumpPolygon };
    
    if (yardPoly.length === 0) {
        const { yardWidth, yardHeight, yardPadding } = DEFAULT_CONFIG;
        yardPoly = [
            { x: yardPadding, y: yardPadding },
            { x: yardWidth - yardPadding, y: yardPadding },
            { x: yardWidth - yardPadding, y: yardHeight - yardPadding },
            { x: yardPadding, y: yardHeight - yardPadding }
        ];
    }
    
    try {
      if (DEMO_LOOP_MODE) {
        zones = assignZones(grid);
        trucks = createTrucks(zones, ep, state.fleetConfig);
      } else {
        const res = await fetch(`${API_BASE}/init_yard`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            polygon: yardPoly,
            entry_point: ep,
            scenario: {
              dump_polygon: scenario.dumpPolygon,
              material_type: scenario.material.type,
              slope_limits: {
                max_cell_slope: scenario.slopeLimits.maxCellSlope,
                max_average_slope: scenario.slopeLimits.maxAverageSlope,
              },
              weather: {
                rain_intensity: scenario.weather.rainIntensity,
                wind_speed: scenario.weather.windSpeed,
                wind_direction_deg: scenario.weather.windDirectionDeg,
                visibility_m: scenario.weather.visibilityM,
              },
            },
          })
        });
        const data = await res.json();

        zones = data.zones.map((z: any) => ({
          id: z.id,
          name: z.name,
          center: { x: 0, y: 0 },
          color: z.color,
          cells: [],
          dumpCount: 0,
          polygonPoints: z.polygon
        }));

        zones.forEach(z => {
          if ((z as any).polygonPoints && (z as any).polygonPoints.length > 0) {
            const pts = (z as any).polygonPoints;
            z.center = {
              x: pts.reduce((sum: number, p: Point) => sum + p.x, 0) / pts.length,
              y: pts.reduce((sum: number, p: Point) => sum + p.y, 0) / pts.length
            };
          }
        });

        for(let r=0; r<grid.length; r++) {
          for(let c=0; c<grid[r].length; c++) {
            const cell = grid[r][c];
            if (yardPoly.length >= 3 && !pointInPolygon(cell, yardPoly)) {
              cell.zoneId = -1;
              continue;
            }

            let bestZone = -1;
            let minDist = Infinity;
            for (let z=0; z<zones.length; z++) {
              const d = distance(cell, zones[z].center);
              if (d < minDist) { minDist = d; bestZone = z; }
            }
            cell.zoneId = bestZone;
            if (bestZone >= 0) zones[bestZone].cells.push(cell);
          }
        }

        trucks = createTrucks(zones, ep, state.fleetConfig);
        for(const t of trucks) {
          await registerTruckWithBackend(t);
        }
      }
    } catch (e) {
      console.error('Error initializing yard context via Backend API', e);
      if (zones.length === 0) {
        zones = assignZones(grid);
      }
      if (trucks.length === 0) {
        trucks = createTrucks(zones, ep, state.fleetConfig);
      }
    }

    set({
      grid,
      zones,
      trucks,
      blockedCells: [],
      piles: [],
      currentZoneIndex: 0,
      tick: 0,
      running: false,
      metrics: {
        totalDumps: 0,
        missedDumps: 0,
        avgSpacing: 1.0,
        packingDensity: 0,
        densityHistory: [0],
        spacingHistory: [1.0],
        zoneDumps: zones.map(() => 0),
        timeSteps: 0,
        maxPeakDistance: 0,
        peakPoints: null,
      },
      scenario,
    });
  },

  start: () => {
    set({ running: true });
    if (!DEMO_LOOP_MODE) {
      startBackendLoop();
    }
  },
  pause: () => {
    if (!DEMO_LOOP_MODE) {
      stopBackendLoop();
    }
    set({ running: false });
  },
  reset: async () => {
    if (!DEMO_LOOP_MODE) {
      stopBackendLoop();
    }
    await get().init();
  },
  setSpeed: (s) => set({ speed: s }),
  setViewMode: (m) => set({ viewMode: m }),
  toggleHeatmap: () => set(s => ({ showHeatmap: !s.showHeatmap })),
  setFleetCounts: async (config) => {
    set({ fleetConfig: { small: Math.max(0, config.small), large: Math.max(0, config.large) } });
    await get().init();
  },
  
  startDrawingMode: () => set({ 
    isDrawing: true, 
    polygonVertices: [], 
    yardPolygon: [], 
    settingEntryPoint: false, 
    entryPoint: null, 
    running: false,
    trucks: [],
    blockedCells: [],
    zones: [],
    piles: [],
    grid: createGrid() // empty grid to start
  }),
  
  addPolygonVertex: (p) => set(state => ({
    polygonVertices: [...state.polygonVertices, p]
  })),
  
  finishPolygon: () => set(state => {
    if (state.polygonVertices.length >= 3) {
      return { isDrawing: false, settingEntryPoint: true, yardPolygon: [...state.polygonVertices] };
    }
    return { isDrawing: false, polygonVertices: [] };
  }),
  
  setEntryPointMode: () => set({ settingEntryPoint: true, running: false }),
  setEntryPoint: (p) => set({ settingEntryPoint: false, entryPoint: p }),
  
  resetDrawing: () => set({ isDrawing: false, settingEntryPoint: false, polygonVertices: [], entryPoint: null, yardPolygon: [] }),
  
  submitCustomYard: async () => {
     await get().init();
  },

  step: () => {
    const state = get();
    if (!state.running) return;

    if (!DEMO_LOOP_MODE) {
      // Backend-driven mode: UI reflects backend state only.
      return;
    }

    const { grid, zones, trucks, metrics, speed, currentZoneIndex } = state;
    const newTrucks = trucks.map(t => ({ ...t }));
    let newDumps = 0;
    let missedThisStep = 0;
    let zoneIdx = currentZoneIndex;

    const activeZone = zones[zoneIdx];
    if (activeZone && isZoneComplete(activeZone, grid)) {
      zoneIdx = Math.min(zoneIdx + 1, zones.length - 1);
    }

    for (const truck of newTrucks) {
      const effectiveSpeed = truck.speed * speed;

      switch (truck.state) {
        case 'idle': {
            truck.waitingSteps = 0;
            truck.deadlocked = false;
            if (DEMO_LOOP_MODE) {
              const demoTarget = getDemoDumpTarget(truck, zones, state.piles, newTrucks, state.yardPolygon);
              truck.targetX = demoTarget.x;
              truck.targetY = demoTarget.y;
              truck.path = null;
              truck.pathIndex = 0;
              truck.state = 'moving_to_dump';
              break;
            }
            truck.state = 'requesting_dump';
            requestDump(truck.id, truck.x, truck.y, truck.assignedZone);
            break;
        }

        case 'requesting_dump': {
          truck.waitingSteps = 0;
          truck.deadlocked = false;
            // Waiting for backend API to respond. Do nothing.
            break;
        }

        case 'moving_to_dump': {
          truck.waitingSteps = 0;
          truck.deadlocked = false;
            if (!DEMO_LOOP_MODE) {
              const avoid = avoidCollisions(truck, newTrucks);
              if (avoid.stop) {
                break;
              }
            } else if (shouldYieldInDemo(truck, newTrucks)) {
              break;
            }

            // Follow Backend A* Path
            if (!DEMO_LOOP_MODE && truck.path && truck.pathIndex < truck.path.length) {
              const nextPt = truck.path[truck.pathIndex];
              const arrivedNode = moveToward(truck, nextPt.x, nextPt.y, effectiveSpeed);
              if (arrivedNode) {
                  truck.pathIndex++;
              }
            } else {
              // Path finished or no path
              const arrivedFinal = DEMO_LOOP_MODE
                ? moveTowardDirect(truck, truck.targetX, truck.targetY, effectiveSpeed)
                : moveToward(truck, truck.targetX, truck.targetY, effectiveSpeed);
              if (arrivedFinal) {
                  truck.state = 'dumping';
                  truck.dumpTimer = DEMO_LOOP_MODE ? 45 : DEFAULT_CONFIG.dumpDuration;
              }
            }
            break;
        }

        case 'dumping': {
          truck.waitingSteps = 0;
          truck.deadlocked = false;
          truck.dumpTimer -= speed;
          if (truck.dumpTimer <= 0) {
            const radius = getDumpRadiusForTruck(truck);
            applyDumpToGrid(grid, { x: truck.targetX, y: truck.targetY }, truck, state.scenario);
            state.piles.push({ x: truck.targetX, y: truck.targetY, radius });
            
            truck.dumpCount++;
            newDumps++;
            if (zones[truck.assignedZone]) {
              zones[truck.assignedZone].dumpCount++;
            }
            
            playDumpSound();
            
            truck.state = 'requesting_return';
            const ep = state.entryPoint || ENTRY_POINT;
            truck.targetX = ep.x;
            truck.targetY = ep.y + getTruckStagingOffset(truck.id, newTrucks.length);
            if (DEMO_LOOP_MODE) {
              truck.path = null;
              truck.pathIndex = 0;
              truck.state = 'returning';
            } else {
              finishDumpAndReturn(truck.id, truck.assignedZone, truck.x, truck.y, { x: truck.targetX, y: truck.targetY });
            }
            truck.targetCell = null;
          }
          break;
        }

        case 'requesting_return': {
          truck.waitingSteps = 0;
          truck.deadlocked = false;
            // Waiting for backend API to respond. Do nothing.
            break;
        }

        case 'returning': {
          truck.waitingSteps = 0;
          truck.deadlocked = false;
          if (!DEMO_LOOP_MODE) {
            const avoid = avoidCollisions(truck, newTrucks);
            if (avoid.stop) {
              break;
            }
          } else if (shouldYieldInDemo(truck, newTrucks)) {
            break;
          }
          
          if (!DEMO_LOOP_MODE && truck.path && truck.pathIndex < truck.path.length) {
              const nextPt = truck.path[truck.pathIndex];
              const arrivedNode = moveToward(truck, nextPt.x, nextPt.y, effectiveSpeed);
              if (arrivedNode) {
                  truck.pathIndex++;
              }
          } else {
              const arrivedFinal = DEMO_LOOP_MODE
                ? moveTowardDirect(truck, truck.targetX, truck.targetY, effectiveSpeed)
                : moveToward(truck, truck.targetX, truck.targetY, effectiveSpeed);
              if (arrivedFinal) {
                truck.state = 'idle';
                truck.path = null;
                truck.pathIndex = 0;
              }
          }
          break;
        }

        case 'waiting': {
          truck.waitingSteps += 1;
          if (truck.waitingSteps > DEADLOCK_WAIT_STEPS) {
            truck.deadlocked = true;
          }
          truck.waitTimer -= speed;
          if (truck.waitTimer <= 0) {
            truck.state = 'idle';
            truck.waitingSteps = 0;
            truck.deadlocked = false;
          }
          break;
        }
      }
    }

    const deadlockedTrucks = newTrucks.filter(t => t.state === 'waiting' && t.waitingSteps > DEADLOCK_WAIT_STEPS);
    if (deadlockedTrucks.length > 0) {
      const lowestPriorityTruck = deadlockedTrucks.reduce((lowest, candidate) => {
        return deadlockPriority(candidate) < deadlockPriority(lowest) ? candidate : lowest;
      });

      lowestPriorityTruck.deadlocked = true;

      if (!DEMO_LOOP_MODE) {
        releaseReservation(lowestPriorityTruck.id);
        lowestPriorityTruck.state = 'requesting_dump';
        lowestPriorityTruck.waitTimer = 0;
        lowestPriorityTruck.waitingSteps = 0;
        lowestPriorityTruck.deadlocked = false;
        requestDump(lowestPriorityTruck.id, lowestPriorityTruck.x, lowestPriorityTruck.y, lowestPriorityTruck.assignedZone);
      } else {
        lowestPriorityTruck.state = 'idle';
        lowestPriorityTruck.waitTimer = 0;
        lowestPriorityTruck.waitingSteps = 0;
        lowestPriorityTruck.deadlocked = false;
      }
    }

    let totalCells = 0;
    let filledCells = 0;
    for (const row of grid) {
       for (const cell of row) {
          if (cell.zoneId !== -1) {
             totalCells++;
           if (cell.filled || cell.height > 0) filledCells++;
          }
       }
    }
    const density = totalCells > 0 ? (filledCells / totalCells) * 100 : 0;
    
    let avgPeakDistance = metrics.maxPeakDistance || 0;
    
    if (newDumps > 0 && state.piles.length >= 2) {
       let totalNearestDist = 0;
       let count = 0;
       for (let i = 0; i < state.piles.length; i++) {
          let minDist = Infinity;
          for (let j = 0; j < state.piles.length; j++) {
             if (i === j) continue;
             const d = distance(state.piles[i], state.piles[j]);
             if (d < minDist) minDist = d;
          }
          if (minDist !== Infinity) {
             totalNearestDist += minDist;
             count++;
          }
       }
       avgPeakDistance = count > 0 ? totalNearestDist / count : 0;
    }

    const newMetrics: SimMetrics = {
      totalDumps: metrics.totalDumps + newDumps,
      missedDumps: metrics.missedDumps + missedThisStep,
      avgSpacing: 1.0,
      packingDensity: Math.round(density * 10) / 10,
      densityHistory: [...metrics.densityHistory, Math.round(density * 10) / 10].slice(-60),
      spacingHistory: [...(metrics.spacingHistory ?? []), 1.0].slice(-60),
      zoneDumps: zones.map(z => z.dumpCount),
      timeSteps: metrics.timeSteps + 1,
      maxPeakDistance: avgPeakDistance,
      peakPoints: null
    };

    set({
      trucks: newTrucks,
      grid: [...grid],
      metrics: newMetrics,
      tick: state.tick + 1,
      currentZoneIndex: zoneIdx,
    });
  },
}));
