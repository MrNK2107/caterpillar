import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { useSimulationStore } from '@/simulation/store';

// DSDE Strategy Panel - shows real-time strategy from DSDE
export const StrategyPanel: React.FC = () => {
  const { metrics } = useSimulationStore();
  
  const activeStrategy = metrics?.strategy?.active || 'S1';
  const strategyReason = metrics?.strategy?.reason || 'initializing';
  const transitionPending = metrics?.strategy?.transition_pending || false;
  const pendingStrategy = metrics?.strategy?.pending || null;
  
  // Get strategy display info
  const strategyInfo = getStrategyInfo(activeStrategy);
  
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
            style={{ backgroundColor: strategyInfo.color + '33', borderColor: strategyInfo.color }}
            className="text-lg font-bold px-3 py-1"
          >
            {activeStrategy}
          </Badge>
          <span className="text-sm text-slate-400">{strategyInfo.name}</span>
        </div>
        
        {/* Reason */}
        <div className="text-xs text-slate-400">
          <span className="font-semibold">Reason: </span>
          {strategyReason}
        </div>
        
        {/* Transition countdown (if pending) */}
        {transitionPending && pendingStrategy && (
          <div className="space-y-1">
            <div className="text-xs text-amber-400">
              Switching to {pendingStrategy} in{' '}
              <span className="font-mono">60s</span>
            </div>
            <Progress value={75} className="h-1 bg-slate-800" />
          </div>
        )}
        
        {/* Modifiers as tags */}
        <div className="flex flex-wrap gap-1 pt-1">
          {getModifiers(activeStrategy).map(mod => (
            <Badge key={mod} variant="secondary" className="text-xs">
              {mod}
            </Badge>
          ))}
          <Badge variant={activeStrategy.includes('S6') ? "destructive" : "default"} className="text-xs">
            {activeStrategy.includes('S6') ? 'S6 ACTIVE' : 'S6 OFF'}
          </Badge>
          <Badge variant={activeStrategy.includes('S7') ? "destructive" : "outline"} className="text-xs">
            {activeStrategy.includes('S7') ? 'S7 FORCED' : 'S7 OK'}
          </Badge>
        </div>
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

function getModifiers(strategy: string): string[] {
  if (strategy.includes('S6')) {
    return ['S6 Active'];
  }
  return [];
}

export default StrategyPanel;