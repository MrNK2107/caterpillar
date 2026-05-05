import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useSimulationStore } from '@/simulation/store';

// DSDE Strategy Panel - shows real-time strategy from DSDE
export const StrategyPanel: React.FC = () => {
  const { decisionState, assignmentDiagnostics } = useSimulationStore();

  const activeStrategy = decisionState?.activeStrategy || 'UNKNOWN';
  const strategyReason = decisionState?.reason || 'Strategy not evaluated yet';
  const strategyLabel = decisionState?.strategyLabel || 'Pending evaluation';
  const transitionPending = Boolean(decisionState?.transitionPending);
  const pendingStrategy = decisionState?.pendingStrategy || null;
  const scenarioId = decisionState?.scenarioId || 'custom';
  const scenarioName = decisionState?.scenarioName || 'custom';
  const s6Active = Boolean(decisionState?.s6Active);
  const s7Active = Boolean(decisionState?.s7Active);
  const plannerMode = decisionState?.plannerMode || "FALLBACK";
  const plannerModeLabel = decisionState?.plannerModeLabel || plannerMode;
  const plannerModeReason = decisionState?.plannerModeReason || "pending";
  const plannerModeSuppressed = Boolean(decisionState?.plannerModeSuppressed);
  const plannerPhase = decisionState?.plannerPhase || "backfill";
  const plannerPhaseReason = decisionState?.plannerPhaseReason || "pending";
  const spacingPatternStatus = decisionState?.spacingPatternStatus || "inactive";
  const waveId = decisionState?.waveId ?? 0;
  const invariants = decisionState?.s3aInvariantStatus;
  const latestTrace = getLatestAssignmentTrace(assignmentDiagnostics);
  
  return (
    <Card className="bg-slate-900 border-slate-700">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-slate-200 flex items-center justify-between">
          <span>ACTIVE STRATEGY</span>
          {transitionPending && (
            <Badge variant="outline" className="text-amber-400 border-amber-400">
              TRANSITION PENDING
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Strategy Badge */}
        <div className="flex items-center gap-2">
          <Badge
            style={{ backgroundColor: getStrategyInfo(activeStrategy).color + '33', borderColor: getStrategyInfo(activeStrategy).color }}
            className="text-lg font-bold px-3 py-1"
          >
            {activeStrategy}
          </Badge>
          <span className="text-sm text-slate-400">{strategyLabel}</span>
        </div>

        <div className="text-xs text-slate-400">
          <span className="font-semibold">Scenario: </span>
          {scenarioId} - {scenarioName}
        </div>
        <div className="text-xs text-slate-400">
          <span className="font-semibold">Planner Mode: </span>
          {plannerMode} - {plannerModeLabel}
          {plannerModeSuppressed ? " (suppressed by safety override)" : ""}
        </div>

        <div className="text-xs text-slate-400">
          <span className="font-semibold">Reason: </span>
          {strategyReason}
        </div>
        <div className="text-xs text-slate-500">
          <span className="font-semibold">Mode reason: </span>
          {plannerModeReason}
        </div>
        <div className="text-xs text-slate-400">
          <span className="font-semibold">Planner Phase: </span>
          {plannerPhase}
        </div>
        <div className="text-xs text-slate-500">
          <span className="font-semibold">Phase reason: </span>
          {plannerPhaseReason}
        </div>
        <div className="text-xs text-slate-400">
          <span className="font-semibold">Spacing Pattern: </span>
          {spacingPatternStatus}
          <span className="text-slate-500"> (wave {waveId})</span>
        </div>

        {transitionPending && pendingStrategy && (
          <div className="text-xs text-amber-400">
            Transition pending to {pendingStrategy}
          </div>
        )}

        <div className="flex flex-wrap gap-1 pt-1">
          <Badge variant={s6Active ? "destructive" : "outline"} className="text-xs">
            {s6Active ? 'S6 ON' : 'S6 OFF'}
          </Badge>
          <Badge variant={s7Active ? "destructive" : "outline"} className="text-xs">
            {s7Active ? 'S7 ON' : 'S7 OFF'}
          </Badge>
        </div>

        <div className="rounded border border-slate-800 bg-slate-950/70 p-2 text-xs text-slate-300">
          <div className="font-semibold text-slate-200">Dump Spot Selection</div>
          <div>
            <span className="text-slate-500">Approach now: </span>
            {latestTrace?.selected_planner_mode ? `${latestTrace.selected_planner_mode} (${latestTrace.candidate_source ?? "unknown"})` : (latestTrace?.candidate_source ?? `${plannerMode} pending`)}
          </div>
          <div>
            <span className="text-slate-500">Anchor band: </span>
            {latestTrace?.anchor_band ?? "N/A"}
            <span className="text-slate-500"> | Wave: </span>
            {latestTrace?.wave_id ?? waveId}
            <span className="text-slate-500"> | Parity: </span>
            {latestTrace?.slot_parity ?? "N/A"}
          </div>
          <div>
            <span className="text-slate-500">Slot: </span>
            {latestTrace?.slot_id ?? "N/A"}
            <span className="text-slate-500"> | Row: </span>
            {latestTrace?.row_id ?? "N/A"}
            <span className="text-slate-500"> | State: </span>
            {latestTrace?.slot_state ?? "N/A"}
          </div>
          <div>
            <span className="text-slate-500">Reserve class: </span>
            {latestTrace?.reserve_class ?? "N/A"}
            <span className="text-slate-500"> | Fallback: </span>
            {latestTrace?.fallback_reason ?? "none"}
          </div>
          <div>
            <span className="text-slate-500">Why selected: </span>
            {latestTrace?.strategy_reason ?? strategyReason}
          </div>
          <div>
            <span className="text-slate-500">Current blocker: </span>
            {latestTrace?.selected_xy ? "none" : (latestTrace?.queue_state ?? latestTrace?.explainability ?? "awaiting assignment")}
          </div>
          <div>
            <span className="text-slate-500">Last strategy eval: </span>
            {decisionState?.lastStrategyEvalTs ? new Date(decisionState.lastStrategyEvalTs * 1000).toLocaleTimeString() : "N/A"}
          </div>
          <div>
            <span className="text-slate-500">Last successful assignment: </span>
            {decisionState?.lastSuccessfulAssignmentTs ? new Date(decisionState.lastSuccessfulAssignmentTs * 1000).toLocaleTimeString() : "N/A"}
          </div>
        </div>

        {plannerMode === "S3A" && (
          <div className="rounded border border-slate-800 bg-slate-950/70 p-2 text-xs text-slate-300">
            <div className="font-semibold text-slate-200">S3A Invariant Status</div>
            <div>Far-end gate: {invariants?.far_end_gate ? "PASS" : "FAIL"}</div>
            <div>Parity gate: {invariants?.parity_gate ? "PASS" : "FAIL"}</div>
            <div>Anchor gap gate: {invariants?.anchor_gap_gate ? "PASS" : "FAIL"}</div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

function getStrategyInfo(strategy: string) {
  const strategies: Record<string, { name: string; color: string }> = {
    'S1': { name: 'Pre-Computed Grid', color: '#22C55E' },
    'S2': { name: 'Polygon-Aware Grid', color: '#3B82F6' },
    'S3': { name: 'Real-Time Adaptive', color: '#F59E0B' },
    'S4': { name: 'Polygon-Constrained Adaptive', color: '#8B5CF6' },
    'S5': { name: 'P2P Sequential', color: '#EC4899' },
    'S6': { name: 'Safety-Priority Modifier', color: '#EF4444' },
    'S7': { name: 'Degraded-Mode Fallback', color: '#DC2626' },
  };
  
  // Extract base strategy
  const base = strategy.replace(/\+.*$/, '');
  return strategies[base] || { name: 'Unknown', color: '#64748B' };
}

function getLatestAssignmentTrace(assignmentDiagnostics: Record<string, { assignment_trace?: Record<string, any> }>) {
  for (const value of Object.values(assignmentDiagnostics || {})) {
    if (value?.assignment_trace) {
      return value.assignment_trace;
    }
  }
  return null;
}

export default StrategyPanel;
