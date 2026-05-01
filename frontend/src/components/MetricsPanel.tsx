import React from 'react';
import { useSimulationStore } from '@/simulation/store';
import { DEFAULT_CONFIG } from '@/simulation/config';
import { Line } from 'react-chartjs-2';
import { Minus, Plus } from 'lucide-react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Filler,
} from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Filler);

function computePolygonArea(points: { x: number; y: number }[]) {
  if (points.length < 3) return 0;

  let area = 0;
  for (let i = 0; i < points.length; i++) {
    const next = (i + 1) % points.length;
    area += points[i].x * points[next].y - points[next].x * points[i].y;
  }

  return Math.abs(area) / 2;
}

function computePolygonBounds(points: { x: number; y: number }[]) {
  if (points.length === 0) {
    return { width: 0, height: 0 };
  }

  const xs = points.map(point => point.x);
  const ys = points.map(point => point.y);

  return {
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
  };
}

const KpiCard: React.FC<{ label: string; value: string | number; accent?: boolean }> = ({ label, value, accent }) => (
  <div className="panel-card p-3">
    <div className="kpi-label">{label}</div>
    <div className={`kpi-value mt-1 ${accent ? 'text-accent' : 'text-foreground'}`}>{value}</div>
  </div>
);

const FleetCountButton: React.FC<{ onClick: () => void; disabled?: boolean; children: React.ReactNode }> = ({ onClick, disabled, children }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
  >
    {children}
  </button>
);

const TruckRow: React.FC<{ label: string; truck: { label: string; state: string; dumpCount: number } }> = ({ label, truck }) => (
  <div className="flex items-center justify-between rounded-lg border border-border/80 bg-background px-3 py-2.5">
    <div className="min-w-0">
      <div className="text-xs font-semibold uppercase tracking-wide text-foreground">{label}</div>
      <div className="text-xs text-muted-foreground font-mono-data">{truck.label}</div>
    </div>
    <div className="flex items-center gap-2">
      <span className="rounded-md bg-muted px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-foreground">
        {truck.state.replace('_', ' ')}
      </span>
      <span className="rounded-md border border-border bg-card px-2 py-1 font-mono-data text-xs font-bold text-foreground">
        {truck.dumpCount}
      </span>
    </div>
  </div>
);

const MetricsPanel: React.FC = () => {
  const { metrics, trucks, fleetConfig, yardPolygon, setFleetCounts } = useSimulationStore();

  const activeTrucks = trucks.filter(t => t.state !== 'idle').length;
  const largeTrucks = trucks.filter(truck => truck.model.payload_tonnes >= 220);
  const smallTrucks = trucks.filter(truck => truck.model.payload_tonnes < 220);
  const fieldArea = computePolygonArea(yardPolygon);
  const fieldBounds = computePolygonBounds(yardPolygon);
  const fieldScaleX = fieldBounds.width > 0 ? fieldBounds.width / DEFAULT_CONFIG.gridCols : DEFAULT_CONFIG.cellSize;
  const fieldScaleY = fieldBounds.height > 0 ? fieldBounds.height / DEFAULT_CONFIG.gridRows : DEFAULT_CONFIG.cellSize;
  const hasPolygon = yardPolygon.length >= 3;

  const updateFleet = (size: 'small' | 'large', delta: number) => {
    const next = {
      ...fleetConfig,
      [size]: Math.max(0, fleetConfig[size] + delta),
    };
    setFleetCounts(next);
  };

  const renderGroup = (title: string, groupTrucks: typeof trucks) => (
    <div className="panel-card p-3 space-y-3">
      <div className="flex items-center justify-between text-xs font-semibold tracking-widest uppercase text-muted-foreground">
        <span>{title}</span>
        <span className="rounded-md bg-muted px-2 py-0.5 text-foreground">{groupTrucks.length}</span>
      </div>
      <div className="space-y-2">
        {groupTrucks.map((truck, index) => (
          <TruckRow
            key={truck.id}
            label={`Truck ${index + 1}`}
            truck={truck}
          />
        ))}
      </div>
    </div>
  );

  const scaling = (200 / DEFAULT_CONFIG.yardWidth);
  const scaledSpacing = metrics.spacingHistory ? metrics.spacingHistory.map(v => v * scaling) : [0];

  const densityChartData = {
    labels: scaledSpacing.map((_, i) => i.toString()),
    datasets: [
      {
        label: 'Current Spacing (m)',
        data: scaledSpacing,
        borderColor: '#FACC15',
        backgroundColor: 'rgba(239, 68, 68, 0.2)', // Red shade for waste area
        fill: 1, // fill to the target line (dataset index 1)
        tension: 0.4,
        pointRadius: 0,
        borderWidth: 2,
      },
      {
        label: 'Target (3.03m)',
        data: scaledSpacing.map(() => 3.03),
        borderColor: '#22C55E',
        borderDash: [5, 5],
        fill: false,
        pointRadius: 0,
        borderWidth: 2,
      },
      {
        label: 'Baseline (7.38m)',
        data: scaledSpacing.map(() => 7.38),
        borderColor: '#EF4444',
        borderDash: [5, 5],
        fill: false,
        pointRadius: 0,
        borderWidth: 2,
      }
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { tooltip: { enabled: true }, title: { display: false } },
    scales: {
      x: {
        display: false,
        grid: { display: false },
      },
      y: {
        beginAtZero: true,
        grid: { color: '#F3F4F6' },
        ticks: { font: { size: 9, family: 'JetBrains Mono' }, color: '#9CA3AF' },
      },
    },
  };

  return (
    <div className="w-[42rem] border-l border-border bg-card flex flex-col overflow-hidden">
      <div className="p-3 border-b border-border">
        <h2 className="text-xs font-semibold text-muted-foreground tracking-widest uppercase">Live Metrics</h2>
      </div>

      <div className="flex-1 overflow-hidden p-3">
        <div className="grid h-full grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] gap-4">
          <div className="flex min-w-0 flex-col gap-3 overflow-hidden">
            <div className="panel-card p-3">
              <div className="text-xs font-semibold text-muted-foreground tracking-widest uppercase mb-1">Drawn Field</div>
              <div className="text-sm font-semibold text-foreground">
                {hasPolygon ? `${yardPolygon.length} vertices` : 'Waiting for polygon'}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {hasPolygon
                  ? `Area ${fieldArea.toFixed(1)} sq units · Scale ${fieldScaleX.toFixed(1)} x ${fieldScaleY.toFixed(1)} units per grid cell`
                  : 'Draw and finish the yard polygon to calculate the field area.'}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <KpiCard label="Total Dumps" value={metrics.totalDumps} accent />
              <KpiCard label="Peak Dist" value={`${metrics.maxPeakDistance ? (metrics.maxPeakDistance * (200 / DEFAULT_CONFIG.yardWidth)).toFixed(1) : 0}m`} />
              <KpiCard label="Density" value={`${metrics.packingDensity}%`} accent />
              <KpiCard label="Active" value={`${activeTrucks}/${trucks.length}`} />
            </div>

            <div className="panel-card p-3 flex-none">
              <div className="text-xs font-semibold text-muted-foreground tracking-widest uppercase mb-2">Spacing Trend</div>
              <div className="h-[140px]">
                <Line data={densityChartData} options={chartOptions as any} />
              </div>
            </div>
            
            <div className="panel-card p-3 min-h-0 flex-1 flex flex-col">
              <div className="text-xs font-semibold text-muted-foreground tracking-widest uppercase mb-2">Live Message Log</div>
              <div className="flex-1 overflow-y-auto space-y-1 font-mono-data text-[10px]">
                {useSimulationStore().messageLog?.map((msg) => (
                  <div key={msg.id} className="flex items-start gap-2">
                    <span className="text-muted-foreground shrink-0">{new Date(msg.timestamp).toISOString().split('T')[1].slice(0, 12)}</span>
                    <span className={`shrink-0 font-bold ${msg.source === 'MQTT' ? 'text-green-500' : 'text-orange-500'}`}>
                      [{msg.source}]
                    </span>
                    <span className="text-foreground">{msg.text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="flex min-w-0 flex-col gap-3 overflow-hidden">
            <div className="panel-card p-3 space-y-3">
              <div className="text-xs font-semibold text-muted-foreground tracking-widest uppercase">Fleet Configuration</div>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-foreground">Large trucks</div>
                  <div className="text-xs text-muted-foreground">Cat 793F / 794 AC / 797F</div>
                </div>
                <div className="flex items-center gap-2">
                  <FleetCountButton onClick={() => updateFleet('large', -1)} disabled={fleetConfig.large === 0}>
                    <Minus size={12} />
                  </FleetCountButton>
                  <span className="min-w-6 text-center font-mono-data text-sm font-semibold text-foreground">{fleetConfig.large}</span>
                  <FleetCountButton onClick={() => updateFleet('large', 1)}>
                    <Plus size={12} />
                  </FleetCountButton>
                </div>
              </div>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-foreground">Small trucks</div>
                  <div className="text-xs text-muted-foreground">Cat 777G / 785 / 789D</div>
                </div>
                <div className="flex items-center gap-2">
                  <FleetCountButton onClick={() => updateFleet('small', -1)} disabled={fleetConfig.small === 0}>
                    <Minus size={12} />
                  </FleetCountButton>
                  <span className="min-w-6 text-center font-mono-data text-sm font-semibold text-foreground">{fleetConfig.small}</span>
                  <FleetCountButton onClick={() => updateFleet('small', 1)}>
                    <Plus size={12} />
                  </FleetCountButton>
                </div>
              </div>
              <div className="flex items-center justify-between rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                <span>Total fleet</span>
                <span className="font-mono-data font-semibold text-foreground">{trucks.length}</span>
              </div>
            </div>

            <div className="space-y-3 min-h-0 flex-1">
              {renderGroup('Large trucks', largeTrucks)}
              {renderGroup('Small trucks', smallTrucks)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MetricsPanel;
