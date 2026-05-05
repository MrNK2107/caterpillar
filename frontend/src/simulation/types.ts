export interface Point {
  x: number;
  y: number;
}

export type MaterialType = 'rock' | 'sand' | 'clay' | 'ore';

export interface MaterialProfile {
  type: MaterialType;
  spreadFactor: number;
  angleOfReposeDeg: number;
  materialMoisturePct: number;
}

export interface MaterialSettledProfile {
  settledWidthRatio: number;
  peakDecay: number;
  baseTargetSpacingM: number;
  nudgeThresholdPct: number;
  nudgeAmountM: number;
}

// Dynamic spacing state - tracks real-time adjustment
export interface DynamicSpacingState {
  // Current target spacing (meters), adjusts based on feedback
  currentTargetSpacingM: number;
  // Running average measured gap from sensor data
  measuredGapM: number;
  // Number of samples in the running average
  sampleCount: number;
  // Last nudge applied (positive = increase, negative = decrease)
  lastNudgeM: number;
  // Whether spacing has been adjusted at least once
  hasAdjusted: boolean;
  // Material type this state applies to
  materialType: MaterialType;
}

export interface SlopeLimits {
  maxCellSlope: number;
  maxAverageSlope: number;
}

export interface WeatherConfig {
  rainIntensity: number;
  windSpeed: number;
  windDirectionDeg: number;
  visibilityM: number;
}

export interface PackingObjectiveWeights {
  coverage: number;
  slopeSafety: number;
  spacing: number;
  laneSpread: number;
}

export interface ScenarioConfig {
  dumpPolygon: Point[];
  material: MaterialProfile;
  slopeLimits: SlopeLimits;
  weather: WeatherConfig;
  packingObjective: PackingObjectiveWeights;
}

export interface GridCell {
  row: number;
  col: number;
  x: number;
  y: number;
  height: number;
  filled: boolean;
  zoneId: number;
}

export interface Pile {
  x: number;
  y: number;
  radius: number;
}

export interface FleetConfig {
  small: number;
  large: number;
  byModel?: Record<string, number>;
}

export interface TruckModelSpec {
  model_name: string;
  payload_tonnes: number;
  width_m: number;
  length_m: number;
  turning_radius_m: number;
  pile_length_m: number;
  pile_width_m: number;
}

export interface Zone {
  id: number;
  center: Point;
  color: string;
  cells: GridCell[];
  dumpCount: number;
}
export type TruckState = 'idle' | 'requesting_dump' | 'moving_to_dump' | 'dumping' | 'requesting_return' | 'returning' | 'waiting';
export interface Truck {
  id: number;
  label: string;
  modelName: string;
  model: TruckModelSpec;
  x: number;
  y: number;
  angle: number;
  vx: number;
  vy: number;
  targetX: number;
  targetY: number;
  speed: number;
  state: TruckState;
  assignedZone: number;
  dumpCount: number;
  targetCell: { row: number; col: number } | null;
  path: Point[] | null;
  pathIndex: number;
  waitTimer: number;
  waitingSteps: number;
  deadlocked: boolean;
  dumpTimer: number;
  color: string;
  zoneName: string;
  runtimeDiagnostics?: {
    speedLimiter: string;
    effectiveSpeed: number;
    expectedSpeed: number;
    blockedBy: string;
    ticksSinceProgress: number;
  };
}

export interface SimMetrics {
  totalDumps: number;
  missedDumps: number;
  avgSpacing: number;
  packingDensity: number;
  densityHistory: number[];
  spacingHistory: number[];
  zoneDumps: number[];
  timeSteps: number;
  maxPeakDistance?: number;
  peakPoints?: [Point, Point] | null;
}

export interface SimConfig {
  gridRows: number;
  gridCols: number;
  cellSize: number;
  numTrucks: number;
  numZones: number;
  truckSpeed: number;
  dumpDuration: number;
  yardWidth: number;
  yardHeight: number;
  yardPadding: number;
}

export interface DecisionState {
  activeStrategy: string;
  strategyLabel: string;
  reason: string;
  scenarioId: string;
  scenarioName: string;
  plannerMode: string;
  plannerModeLabel: string;
  plannerModeReason: string;
  plannerModeSuppressed: boolean;
  plannerPhase?: string;
  plannerPhaseReason?: string;
  spacingPatternStatus?: string;
  waveId?: number;
  s6Active: boolean;
  s7Active: boolean;
  expectedStrategies: string[];
  triggerState: Record<string, unknown>;
  divergenceSteps: number;
  transitionPending: boolean;
  pendingStrategy: string | null;
  lastStrategyEvalTs: number | null;
  lastSuccessfulAssignmentTs: number | null;
}
