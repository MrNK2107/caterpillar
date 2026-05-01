// Dynamic Spacing Calculator
// Uses predictive model + real-time feedback for optimal pile placement
// No waiting - predictive placement is instant, async measurement adjusts incrementally

import { MATERIAL_SETTLED_PROFILES } from './config';
import type { DynamicSpacingState, MaterialType } from './types';

const DEFAULT_SAMPLES = 5;  // Rolling average window
const NUDGE_THRESHOLD_PCT = 0.15;  // 15% deviation before nudge

export interface SpacingPrediction {
  // The calculated next spot position (in meters from previous pile)
  predictedSpacingM: number;
  // Whether a nudge should be applied
  shouldNudge: boolean;
  // Nudge amount if shouldNudge is true (meters, + = increase, - = decrease)
  nudgeAmountM: number;
  // Reason for the prediction
  reason: string;
}

// Get material profile with fallback
function getMaterialProfile(materialType: string) {
  const typeKey = materialType.toLowerCase() as MaterialType;
  return MATERIAL_SETTLED_PROFILES[typeKey] || MATERIAL_SETTLED_PROFILES.ore;
}

// Predict next spot spacing based on material and current state
export function predictNextSpotSpacing(
  materialType: string,
  truckPileWidth: number,
  previousMeasuredWidth: number | null,
  dynamicState: DynamicSpacingState | null,
): SpacingPrediction {
  const profile = getMaterialProfile(materialType);
  
  // Start with base target from material profile
  let targetSpacing = profile.baseTargetSpacingM;
  
  // If we have dynamic state with prior adjustments, use current target
  if (dynamicState?.hasAdjusted && dynamicState.currentTargetSpacingM > 0) {
    targetSpacing = dynamicState.currentTargetSpacingM;
  }
  
  // Calculate predicted pile footprint using material's settled ratio
  const predictedPileWidth = truckPileWidth * profile.settledWidthRatio;
  
  // Edge-to-edge spacing: previous pile edge + next pile edge (simplified as ratio of widths)
  const edgeToEdge = predictedPileWidth * profile.settledWidthRatio;
  let predictedSpacingM = edgeToEdge;
  
  // If prediction is below material's base target, use the base (safety floor)
  if (predictedSpacingM < profile.baseTargetSpacingM * 0.7) {
    predictedSpacingM = profile.baseTargetSpacingM;
  }
  
  // Now check if we should nudge based on deviation from measured
  let shouldNudge = false;
  let nudgeAmountM = 0;
  
  if (previousMeasuredWidth !== null && previousMeasuredWidth > 0 && dynamicState) {
    const predictedWidth = truckPileWidth * profile.settledWidthRatio;
    const deviationPct = Math.abs(previousMeasuredWidth - predictedWidth) / predictedWidth;
    
    // Only nudge if deviation exceeds threshold
    if (deviationPct > NUDGE_THRESHOLD_PCT) {
      shouldNudge = true;
      // Nudge direction: if actual is smaller than predicted, we can tighten; if larger, we need more space
      if (previousMeasuredWidth < predictedWidth) {
        nudgeAmountM = profile.nudgeAmountM;  // Reduce (materials spread more than predicted)
      } else {
        nudgeAmountM = -profile.nudgeAmountM;  // Increase (materials hold shape more)
      }
    }
  }
  
  // If we have a dynamic state with recent nudge, reverse it first
  if (dynamicState?.lastNudgeM && Math.abs(dynamicState.lastNudgeM) > 0.01) {
    // Apply reverse of last nudge to prevent oscillation
    predictedSpacingM -= dynamicState.lastNudgeM * 0.5;
    // Then add new nudge (if any)
    predictedSpacingM += nudgeAmountM;
  } else {
    predictedSpacingM += nudgeAmountM;
  }
  
  // Safety bounds: don't go below 2.0m or above 5.0m
  predictedSpacingM = Math.max(2.0, Math.min(5.0, predictedSpacingM));
  
  let reason = `material=${materialType}, base=${profile.baseTargetSpacingM}m`;
  if (dynamicState?.hasAdjusted) {
    reason += `, adjusted=${targetSpacing.toFixed(2)}m`;
  }
  if (shouldNudge) {
    reason += `, nudge=${nudgeAmountM.toFixed(2)}m`;
  }
  
  return {
    predictedSpacingM,
    shouldNudge,
    nudgeAmountM,
    reason,
  };
}

// Calculate measured gap from sensor scan data
// Returns the actual peak-to-peak distance after material settles
export function calculateMeasuredGap(
  previousPileX: number,
  previousPileY: number,
  currentPileX: number,
  currentPileY: number,
): number {
  return Math.sqrt(
    Math.pow(currentPileX - previousPileX, 2) + 
    Math.pow(currentPileY - previousPileY, 2)
  );
}

// Update dynamic spacing state based on measured gap
export function updateDynamicSpacingState(
  currentState: DynamicSpacingState | null,
  measuredGapM: number,
  materialType: string,
): DynamicSpacingState {
  const profile = getMaterialProfile(materialType);
  
  if (!currentState) {
    // Initialize state
    return {
      currentTargetSpacingM: profile.baseTargetSpacingM,
      measuredGapM,
      sampleCount: 1,
      lastNudgeM: 0,
      hasAdjusted: false,
      materialType: materialType as MaterialType,
    };
  }
  
  // Update running average of measured gaps
  const newSampleCount = Math.min(currentState.sampleCount + 1, DEFAULT_SAMPLES);
  const runningAvg = (
    (currentState.measuredGapM * currentState.sampleCount + measuredGapM) / newSampleCount
  );
  
  // Calculate deviation from current target
  const deviationPct = Math.abs(runningAvg - currentState.currentTargetSpacingM) / currentState.currentTargetSpacingM;
  
  // Determine if we should adjust
  let newTargetSpacingM = currentState.currentTargetSpacingM;
  let lastNudgeM = currentState.lastNudgeM;
  let hasAdjusted = currentState.hasAdjusted;
  
  if (deviationPct > NUDGE_THRESHOLD_PCT && newSampleCount >= 2) {
    // Adjust target towards measured average (gradual correction)
    const adjustment = (runningAvg - currentState.currentTargetSpacingM) * 0.3;  // 30% of error, gradual
    newTargetSpacingM += adjustment;
    lastNudgeM = adjustment;
    hasAdjusted = true;
    
    // Safety bounds
    newTargetSpacingM = Math.max(2.0, Math.min(5.0, newTargetSpacingM));
  }
  
  return {
    currentTargetSpacingM: newTargetSpacingM,
    measuredGapM: runningAvg,
    sampleCount: newSampleCount,
    lastNudgeM,
    hasAdjusted,
    materialType: materialType as MaterialType,
  };
}

// Get initial spacing for a new dump sequence
export function getInitialSpacing(materialType: string): number {
  const profile = getMaterialProfile(materialType);
  return profile.baseTargetSpacingM;
}

// Check if current spacing is close to target (within tolerance)
export function isSpacingOptimal(
  currentSpacingM: number,
  targetSpacingM: number,
  tolerancePct: number = 0.10,  // 10% tolerance
): boolean {
  const deviation = Math.abs(currentSpacingM - targetSpacingM) / targetSpacingM;
  return deviation <= tolerancePct;
}