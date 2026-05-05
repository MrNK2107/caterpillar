import { MaterialProfile, ScenarioConfig, SimConfig } from './types';

export const DEFAULT_FLEET = {
  small: 4,
  large: 4,
  byModel: {
    'Cat 777G': 2,
    'Cat 785': 1,
    'Cat 789D': 1,
    'Cat 793F': 2,
    'Cat 794 AC': 1,
    'Cat 797F': 1,
  },
};

export const CAT_TRUCK_MODELS = {
  'Cat 777G': {
    model_name: 'Cat 777G',
    payload_tonnes: 100,
    width_m: 7.4,
    length_m: 11.7,
    turning_radius_m: 12.8,
    pile_length_m: 5.5,
    pile_width_m: 4.5,
  },
  'Cat 785': {
    model_name: 'Cat 785',
    payload_tonnes: 139,
    width_m: 8.2,
    length_m: 12.8,
    turning_radius_m: 14.2,
    pile_length_m: 7.0,
    pile_width_m: 5.5,
  },
  'Cat 789D': {
    model_name: 'Cat 789D',
    payload_tonnes: 181,
    width_m: 8.8,
    length_m: 13.5,
    turning_radius_m: 15.8,
    pile_length_m: 8.0,
    pile_width_m: 6.2,
  },
  'Cat 793F': {
    model_name: 'Cat 793F',
    payload_tonnes: 227,
    width_m: 9.3,
    length_m: 15.5,
    turning_radius_m: 17.5,
    pile_length_m: 9.0,
    pile_width_m: 7.0,
  },
  'Cat 797F': {
    model_name: 'Cat 797F',
    payload_tonnes: 363,
    width_m: 9.8,
    length_m: 15.1,
    turning_radius_m: 18.5,
    pile_length_m: 11.0,
    pile_width_m: 8.5,
  },
  'Cat 794 AC': {
    model_name: 'Cat 794 AC',
    payload_tonnes: 290,
    width_m: 9.5,
    length_m: 15.0,
    turning_radius_m: 17.8,
    pile_length_m: 10.0,
    pile_width_m: 7.8,
  },
} as const;

export const CAT_MODEL_GROUPS = {
  small: ['Cat 777G', 'Cat 785', 'Cat 789D'] as const,
  large: ['Cat 793F', 'Cat 794 AC', 'Cat 797F'] as const,
};

export const DEFAULT_CONFIG: SimConfig = {
  gridRows: 20,
  gridCols: 30,
  cellSize: 24,
  numTrucks: 8,
  numZones: 4,
  truckSpeed: 8.0,
  dumpDuration: 60, // 1 second at 60fps
  yardWidth: 720,
  yardHeight: 480,
  yardPadding: 40,
};

export const ZONE_COLORS = [
  'hsla(48, 96%, 53%, 0.35)',
  'hsla(160, 84%, 39%, 0.35)',
  'hsla(199, 89%, 48%, 0.35)',
  'hsla(280, 67%, 55%, 0.35)',
  'hsla(20, 90%, 50%, 0.35)',
  'hsla(340, 80%, 50%, 0.35)',
];

export const ZONE_BORDER_COLORS = [
  'hsla(48, 96%, 53%, 0.9)',
  'hsla(160, 84%, 39%, 0.9)',
  'hsla(199, 89%, 48%, 0.9)',
  'hsla(280, 67%, 55%, 0.9)',
  'hsla(20, 90%, 50%, 0.9)',
  'hsla(340, 80%, 50%, 0.9)',
];

export const TRUCK_COLORS = [
  '#FACC15', '#F59E0B', '#EAB308', '#D97706',
  '#FCD34D', '#FDE68A', '#F59E0B', '#CA8A04',
];

export const ENTRY_POINT = { x: 20, y: 240 };

// Polygon boundary for the dump yard (relative to canvas)
export const YARD_POLYGON: { x: number; y: number }[] = [
  { x: 60, y: 30 },
  { x: 700, y: 30 },
  { x: 710, y: 60 },
  { x: 710, y: 420 },
  { x: 700, y: 450 },
  { x: 60, y: 450 },
  { x: 50, y: 420 },
  { x: 50, y: 60 },
];

export const MATERIAL_PROFILES: Record<string, MaterialProfile> = {
  rock: { type: 'rock', spreadFactor: 0.85, angleOfReposeDeg: 38, materialMoisturePct: 10 },
  sand: { type: 'sand', spreadFactor: 1.25, angleOfReposeDeg: 32, materialMoisturePct: 5 },
  clay: { type: 'clay', spreadFactor: 1.05, angleOfReposeDeg: 30, materialMoisturePct: 20 },
  ore: { type: 'ore', spreadFactor: 0.95, angleOfReposeDeg: 36, materialMoisturePct: 15 },
};

// Material-specific settled pile behavior for dynamic spacing
// These values represent how each material settles after dumping
// Used for predictive spacing - adjusted in real-time based on feedback
export const MATERIAL_SETTLED_PROFILES: Record<string, {
  // Predictive spacing target (multiplier of pile width)
  settledWidthRatio: number;
  // Peak decay after settling (0-1, lower = maintains shape better)
  peakDecay: number;
  // Base target spacing in meters (initial target before feedback)
  baseTargetSpacingM: number;
  // Maximum deviation before nudge adjustment (15% = don't adjust)
  nudgeThresholdPct: number;
  // How much to nudge when deviation detected (- = reduce spacing, + = increase)
  nudgeAmountM: number;
}> = {
  sand: {
    settledWidthRatio: 0.85,  // spreads more when settled - can place closer
    peakDecay: 0.30,         // significant settle
    baseTargetSpacingM: 2.8, // tighter target for sand
    nudgeThresholdPct: 0.15,
    nudgeAmountM: -0.15,    // nudge closer
  },
  coal: {
    settledWidthRatio: 0.92,  // maintains shape reasonably
    peakDecay: 0.15,         // minimal settle
    baseTargetSpacingM: 3.3,  // moderate target
    nudgeThresholdPct: 0.15,
    nudgeAmountM: 0.1,        // slight push
  },
  rock: {
    settledWidthRatio: 0.95,  // holds shape well
    peakDecay: 0.10,          // minimal settle
    baseTargetSpacingM: 3.5,  // conservative
    nudgeThresholdPct: 0.15,
    nudgeAmountM: 0.05,      // minimal nudge
  },
  overburden: {
    settledWidthRatio: 0.90,  // medium behavior
    peakDecay: 0.20,         // moderate settle
    baseTargetSpacingM: 3.0,  // middle ground
    nudgeThresholdPct: 0.15,
    nudgeAmountM: 0.1,       // slight nudge
  },
  ore: {
    settledWidthRatio: 0.88,  // slightly spreads
    peakDecay: 0.18,          // moderate settle
    baseTargetSpacingM: 3.1,   // close to target
    nudgeThresholdPct: 0.15,
    nudgeAmountM: 0.1,        // slight nudge
  },
  clay: {
    settledWidthRatio: 0.82,  // spreads significantly when wet
    peakDecay: 0.35,          // high settle
    baseTargetSpacingM: 2.6,  // tight for clay
    nudgeThresholdPct: 0.15,
    nudgeAmountM: -0.2,       // reduce spacing
  },
};

export const DEFAULT_SCENARIO: ScenarioConfig = {
  dumpPolygon: YARD_POLYGON,
  material: { ...MATERIAL_PROFILES.ore },
  slopeLimits: {
    maxCellSlope: 0.9,
    maxAverageSlope: 0.65,
  },
  weather: {
    rainIntensity: 0.1,
    windSpeed: 4,
    windDirectionDeg: 25,
    visibilityM: 450,
  },
  packingObjective: {
    coverage: 1.5,
    slopeSafety: 1.0,
    spacing: 1.2,
    laneSpread: 0.8,
  },
};
