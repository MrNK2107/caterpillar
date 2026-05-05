import React, { useEffect, useState } from "react";
import { Menu, Play, Pause, RotateCcw, Settings2, Eye, EyeOff, FlaskConical, PencilRuler, MapPin, CheckCircle2, Minus, Plus } from "lucide-react";
import Canvas2D from "./Canvas2D";
import StrategyPanel from "./StrategyPanel";
import ScenarioSelector from "./ScenarioSelector";
import { useSimulationStore } from "@/simulation/store";
import { CAT_TRUCK_MODELS, DEFAULT_CONFIG } from "@/simulation/config";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const KpiTile: React.FC<{ label: string; value: string | number; sub?: string }> = ({ label, value, sub }) => (
  <div className="rounded-md border border-slate-800 bg-slate-900/80 px-3 py-2">
    <div className="text-[10px] uppercase tracking-[0.14em] text-slate-400">{label}</div>
    <div className="mt-1 font-mono text-[1.35rem] font-semibold leading-none text-slate-100">{value}</div>
    {sub ? <div className="mt-1 text-[10px] text-slate-500">{sub}</div> : null}
  </div>
);

const ObjectiveControls: React.FC = () => {
  const { scenario, setPackingObjectiveWeights } = useSimulationStore();

  return (
    <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Packing Objective Weights</div>

      {[
        { key: "coverage", label: "Coverage" },
        { key: "slopeSafety", label: "Slope Safety" },
        { key: "spacing", label: "Spacing" },
        { key: "laneSpread", label: "Lane Spread" },
      ].map(({ key, label }) => {
        const value = scenario.packingObjective[key as keyof typeof scenario.packingObjective];
        return (
          <div key={key}>
            <label className="mb-1 block text-xs text-slate-400">
              {label}: <span className="font-mono text-slate-200">{Number(value).toFixed(2)}</span>
            </label>
            <input
              type="range"
              min={0}
              max={3}
              step={0.1}
              value={value}
              onChange={(event) =>
                void setPackingObjectiveWeights({ [key]: Number(event.target.value) } as Partial<typeof scenario.packingObjective>)
              }
              className="w-full accent-yellow-400"
            />
          </div>
        );
      })}
    </div>
  );
};

const ConfigFleetTab: React.FC = () => {
  const { fleetConfig, setFleetModelCounts } = useSimulationStore();
  const modelCounts = fleetConfig.byModel ?? {};
  const modelNames = Object.keys(CAT_TRUCK_MODELS);
  const total = modelNames.reduce((sum, modelName) => sum + (modelCounts[modelName] ?? 0), 0);

  const changeCount = async (modelName: string, delta: number) => {
    const next: Record<string, number> = {};
    for (const name of modelNames) {
      next[name] = Math.max(0, modelCounts[name] ?? 0);
    }
    next[modelName] = Math.max(0, (next[modelName] ?? 0) + delta);
    await setFleetModelCounts(next);
  };

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Autonomous Fleet Models</div>
        <div className="max-h-[44vh] space-y-2 overflow-y-auto pr-1">
          {modelNames.map((modelName) => {
            const spec = CAT_TRUCK_MODELS[modelName as keyof typeof CAT_TRUCK_MODELS];
            const count = modelCounts[modelName] ?? 0;
            return (
              <div key={modelName} className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-950 px-2 py-2">
                <div className="min-w-0">
                  <div className="truncate text-xs font-semibold text-slate-100">{modelName}</div>
                  <div className="text-[11px] text-slate-500">{spec.payload_tonnes}t payload</div>
                </div>
                <div className="ml-2 flex items-center gap-2">
                  <button className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800" onClick={() => void changeCount(modelName, -1)}>
                    <Minus className="h-3 w-3" />
                  </button>
                  <span className="w-6 text-center font-mono text-sm text-slate-100">{count}</span>
                  <button className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800" onClick={() => void changeCount(modelName, 1)}>
                    <Plus className="h-3 w-3" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-2 rounded border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-slate-400">
          Total configured trucks: <span className="font-mono text-slate-100">{total}</span>
        </div>
      </div>
    </div>
  );
};

const ConfigSimulationTab: React.FC = () => {
  const {
    running,
    start,
    pause,
    reset,
    speed,
    setSpeed,
    showHeatmap,
    toggleHeatmap,
    viewMode,
    setViewMode,
  } = useSimulationStore();

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Run Controls</div>
        <div className="grid grid-cols-3 gap-2">
          <Button
            size="sm"
            className="bg-yellow-400 text-black hover:bg-yellow-300"
            onClick={() => {
              if (running) {
                pause();
              } else {
                void start();
              }
            }}
          >
            {running ? <Pause className="mr-1 h-3.5 w-3.5" /> : <Play className="mr-1 h-3.5 w-3.5" />}
            {running ? "Pause" : "Run"}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => useSimulationStore.getState().step()}>
            Step
          </Button>
          <Button size="sm" variant="outline" onClick={() => void reset()}>
            <RotateCcw className="mr-1 h-3.5 w-3.5" />
            Reset
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Simulation Speed</div>
        <label className="mb-1 block text-xs text-slate-400">Speed: <span className="font-mono text-slate-200">{speed.toFixed(1)}x</span></label>
        <input type="range" min={0.5} max={5} step={0.5} value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))} className="w-full accent-yellow-400" />
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Display</div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={showHeatmap ? "default" : "outline"} onClick={toggleHeatmap} className={showHeatmap ? "bg-yellow-500 text-black hover:bg-yellow-400" : "border-slate-700 text-slate-200"}>
            {showHeatmap ? <Eye className="mr-1 h-3.5 w-3.5" /> : <EyeOff className="mr-1 h-3.5 w-3.5" />}
            Heatmap
          </Button>
          <div className="inline-flex overflow-hidden rounded-md border border-slate-700">
            <button onClick={() => setViewMode("2d")} className={`px-3 py-1.5 text-xs font-semibold ${viewMode === "2d" ? "bg-yellow-400 text-black" : "bg-slate-900 text-slate-300 hover:bg-slate-800"}`}>
              2D
            </button>
            <button onClick={() => setViewMode("3d")} className={`px-3 py-1.5 text-xs font-semibold ${viewMode === "3d" ? "bg-yellow-400 text-black" : "bg-slate-900 text-slate-300 hover:bg-slate-800"}`}>
              3D
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const ConfigScenarioTab: React.FC<{ onBeginDraw: () => void }> = ({ onBeginDraw }) => {
  const [showScenarios, setShowScenarios] = useState(false);
  const { isDrawing, startDrawingMode, finishPolygon, polygonVertices, yardPolygon, settingEntryPoint, setEntryPointMode } = useSimulationStore();

  return (
    <>
      {showScenarios && <ScenarioSelector onClose={() => setShowScenarios(false)} />}
      <div className="space-y-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Scenarios</div>
          <Button size="sm" variant="outline" className="w-full border-slate-700 text-slate-200 hover:bg-slate-800" onClick={() => setShowScenarios(true)}>
            <FlaskConical className="mr-1 h-3.5 w-3.5" />
            Open AHS Scenarios
          </Button>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Map & Entry</div>
          <div className="space-y-2">
            <Button
              size="sm"
              variant="outline"
              className="w-full border-slate-700 text-slate-200 hover:bg-slate-800"
              onClick={() => {
                startDrawingMode();
                onBeginDraw();
              }}
            >
              <PencilRuler className="mr-1 h-3.5 w-3.5" />
              Draw Yard
            </Button>
            {isDrawing ? (
              <Button
                size="sm"
                className="w-full bg-yellow-400 text-black hover:bg-yellow-300"
                onClick={finishPolygon}
                disabled={polygonVertices.length < 3}
              >
                <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
                Finish Polygon
              </Button>
            ) : null}
            {yardPolygon.length >= 3 ? (
              <Button
                size="sm"
                variant="outline"
                className={`w-full border-slate-700 text-slate-200 hover:bg-slate-800 ${settingEntryPoint ? "bg-slate-800" : ""}`}
                onClick={setEntryPointMode}
              >
                <MapPin className="mr-1 h-3.5 w-3.5" />
                {settingEntryPoint ? "Setting Entry Point" : "Change Entry Point"}
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
};

const IntegratedDashboard: React.FC = () => {
  const [isConfigOpen, setIsConfigOpen] = useState(false);
  const {
    init,
    running,
    start,
    pause,
    step,
    reset,
    metrics,
    trucks,
    tick,
    runLoopState,
    backendHealth,
    healthProbeCountWindow,
    assignmentDiagnostics,
    startInFlight,
    yardPolygon,
    messageLog,
    isDrawing,
    settingEntryPoint,
    initPhase,
    initError,
    polygonVertices,
    finishPolygon,
    resetDrawing,
  } = useSimulationStore();

  useEffect(() => {
    void init();
  }, [init]);

  const activeTrucks = trucks.filter((truck) => truck.state !== "idle").length;
  const avgSpacing = Number(metrics?.avgSpacing ?? 0).toFixed(2);
  const packingDensity = `${Number(metrics?.packingDensity ?? 0).toFixed(1)}%`;
  const maxPeakDistance = `${Number(metrics?.maxPeakDistance ?? 0).toFixed(1)} m`;
  const yardUsed = `${Number(metrics?.packingDensity ?? 0).toFixed(1)}%`;
  const aspectRatio = `${DEFAULT_CONFIG.yardWidth} / ${DEFAULT_CONFIG.yardHeight}`;
  const isYardEditing = isDrawing || settingEntryPoint;
  const controlsLocked = isYardEditing;
  const lastTickTime = backendHealth.lastSuccessfulTickAt
    ? new Date(backendHealth.lastSuccessfulTickAt).toLocaleTimeString()
    : "N/A";

  return (
    <div className="h-screen overflow-hidden bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold">Autonomous Truck Dumping Optimisation</h1>
            <p className="text-sm text-slate-400">Backend-authoritative ADPS control loop</p>
          </div>
          <div className="rounded-md border border-emerald-800/60 bg-emerald-950/30 px-3 py-1 text-xs text-emerald-300">
            SYSTEM ONLINE - tick {tick} - {runLoopState.toUpperCase()}
          </div>
        </div>
      </header>

      <div className="border-b border-slate-800 bg-slate-950/95 px-4 py-3">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          <KpiTile label="Total Dumps" value={metrics?.totalDumps ?? 0} />
          <KpiTile label="Yard Used" value={yardUsed} />
          <KpiTile label="Avg Spacing" value={`${avgSpacing} m`} />
          <KpiTile label="Peak Dist" value={maxPeakDistance} />
          <KpiTile label="Active Trucks" value={`${activeTrucks}/${trucks.length}`} />
          <KpiTile label="Yard Vertices" value={yardPolygon.length >= 3 ? yardPolygon.length : "Not set"} />
        </div>
      </div>

      <main className="mx-auto grid h-[calc(100vh-176px)] max-w-[2048px] grid-cols-1 gap-3 p-3 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-2 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Dump Yard</h2>
              <p className="text-xs text-slate-400">
                {isYardEditing
                  ? "Autonomous yard initialization in progress."
                  : "Space-optimized viewport with realistic truck clarity."}
              </p>
            </div>
            <Sheet open={isConfigOpen} onOpenChange={setIsConfigOpen}>
              <SheetTrigger asChild>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-slate-700 bg-slate-900 text-slate-200 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={controlsLocked}
                >
                  <Settings2 className="mr-1 h-4 w-4" />
                  Config
                </Button>
              </SheetTrigger>
              <SheetContent
                side="left"
                className="w-[94vw] overflow-y-auto overflow-x-hidden border-slate-800 bg-slate-950 p-4 text-slate-100 sm:max-w-[460px]"
              >
                <SheetHeader className="mb-3">
                  <SheetTitle className="text-slate-100">Configuration</SheetTitle>
                  <SheetDescription className="text-slate-400">Compact controls tuned for quick edits without clutter.</SheetDescription>
                </SheetHeader>

                <Tabs defaultValue="simulation" className="w-full">
                  <TabsList className="grid w-full grid-cols-5 bg-slate-900 text-slate-300">
                    <TabsTrigger value="simulation" className="text-xs">Sim</TabsTrigger>
                    <TabsTrigger value="scenario" className="text-xs">Scenario</TabsTrigger>
                    <TabsTrigger value="strategy" className="text-xs">Strategy</TabsTrigger>
                    <TabsTrigger value="fleet" className="text-xs">Fleet</TabsTrigger>
                    <TabsTrigger value="weights" className="text-xs">Weights</TabsTrigger>
                  </TabsList>

                  <TabsContent value="simulation" className="space-y-3">
                    <ConfigSimulationTab />
                  </TabsContent>

                  <TabsContent value="scenario" className="space-y-3">
                    <ConfigScenarioTab onBeginDraw={() => setIsConfigOpen(false)} />
                  </TabsContent>

                  <TabsContent value="strategy" className="space-y-3">
                    <StrategyPanel />
                  </TabsContent>

                  <TabsContent value="fleet" className="space-y-3">
                    <ConfigFleetTab />
                  </TabsContent>

                  <TabsContent value="weights" className="space-y-3">
                    <ObjectiveControls />
                  </TabsContent>
                </Tabs>
              </SheetContent>
            </Sheet>
          </div>

          <div className="relative w-full overflow-hidden rounded-lg border border-slate-800 bg-slate-950 p-1">
            <div className="mx-auto h-[calc(100vh-330px)] w-full min-h-[440px]" style={{ aspectRatio }}>
              <Canvas2D />
            </div>
            {isYardEditing && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 p-3">
                <div className="pointer-events-auto mx-auto max-w-3xl rounded-lg border border-slate-700 bg-slate-950/95 px-4 py-3 backdrop-blur">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-xs uppercase tracking-wider text-slate-400">
                        {initPhase === 'drawing' ? 'Step 1/2 - Draw Yard' : 'Step 2/2 - Entry Point'}
                      </div>
                      <div className="text-sm text-slate-100">
                        {initPhase === 'drawing'
                          ? `Add vertices and click near the first point to auto-close (${polygonVertices.length} added).`
                          : 'Click inside the polygon to set the entry point and initialize.'}
                      </div>
                      {initError ? <div className="mt-1 text-xs text-red-400">{initError}</div> : null}
                    </div>
                    <div className="flex items-center gap-2">
                      {initPhase === 'drawing' && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={finishPolygon}
                          disabled={polygonVertices.length < 3}
                        >
                          Finish Polygon
                        </Button>
                      )}
                      <Button size="sm" variant="outline" onClick={resetDrawing}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              className="bg-yellow-400 text-black hover:bg-yellow-300 disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => {
                if (running) {
                  pause();
                } else {
                  void start();
                }
              }}
              size="sm"
              disabled={controlsLocked || startInFlight}
            >
              {running ? <Pause className="mr-1 h-3.5 w-3.5" /> : <Play className="mr-1 h-3.5 w-3.5" />}
              {running ? "Pause" : runLoopState === "error" ? "Retry Run" : "Run"}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => void step()} disabled={controlsLocked}>
              Step
            </Button>
            <Button variant="outline" size="sm" onClick={() => void reset()} disabled={isYardEditing}>
              <RotateCcw className="mr-1 h-3.5 w-3.5" />
              Reset
            </Button>
          </div>
        </section>

        <aside className="flex h-full flex-col gap-3 overflow-hidden">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wider text-slate-400">
              <Menu className="h-3.5 w-3.5" /> Live Strategy
            </div>
            <StrategyPanel />
          </div>

          <div className="min-h-0 flex-1 rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="text-xs uppercase tracking-wider text-slate-400">Fleet & Logs</div>
            <Tabs defaultValue="fleet" className="mt-2 h-[calc(100%-20px)]">
              <TabsList className="grid w-full grid-cols-2 bg-slate-950/70">
                <TabsTrigger value="fleet" className="text-xs">Fleet</TabsTrigger>
                <TabsTrigger value="logs" className="text-xs">Logs</TabsTrigger>
              </TabsList>

              <TabsContent value="fleet" className="mt-2 h-[calc(100%-42px)] space-y-2 overflow-y-auto pr-1">
                {trucks.map((truck) => (
                  <div key={truck.id} className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-950 px-2 py-2 text-xs">
                    <div>
                      <div className="font-mono font-semibold text-yellow-400">T{truck.id + 1}</div>
                      <div className="text-slate-400">{truck.label}</div>
                    </div>
                    <div className="text-right">
                      <div className="capitalize text-slate-200">{truck.state.replace("_", " ")}</div>
                      <div className="font-mono text-slate-500">{truck.dumpCount} dumps</div>
                      {(() => {
                        const diag = assignmentDiagnostics[String(truck.id)] as any;
                        const trace = diag?.assignment_trace as any;
                        const runtime = truck.runtimeDiagnostics;
                        const dx = (truck.targetX ?? truck.x) - truck.x;
                        const dy = (truck.targetY ?? truck.y) - truck.y;
                        const targetDist = Math.hypot(dx, dy);
                        const isFar = targetDist > 140;
                        return (
                          <>
                            {runtime?.speedLimiter && runtime.speedLimiter !== "none" ? (
                              <div className="max-w-[220px] truncate text-[10px] text-amber-300">
                                Slow cause: {runtime.speedLimiter}
                              </div>
                            ) : null}
                            {isFar ? (
                              <div className="max-w-[220px] truncate text-[10px] text-orange-300">
                                Far target: {targetDist.toFixed(0)}m ({trace?.candidate_source ?? "assignment"})
                              </div>
                            ) : null}
                          </>
                        );
                      })()}
                      {truck.state === "requesting_dump" ? (
                        <div className="max-w-[180px] truncate text-[10px] text-amber-300">
                          {(assignmentDiagnostics[String(truck.id)] as any)?.assignment_trace?.queue_state
                            ? `${(assignmentDiagnostics[String(truck.id)] as any).assignment_trace.queue_state}: ${assignmentDiagnostics[String(truck.id)]?.reason ?? ""}`
                            : (assignmentDiagnostics[String(truck.id)]?.reason ?? "Awaiting backend assignment")}
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </TabsContent>

              <TabsContent value="logs" className="mt-2 h-[calc(100%-42px)] space-y-1 overflow-y-auto pr-1 font-mono text-[11px]">
                {(messageLog ?? []).length === 0 ? (
                  <p className="text-slate-500">No events yet.</p>
                ) : (
                  messageLog.slice(-80).reverse().map((entry, idx) => (
                    <div key={`${entry.timestamp}-${idx}`} className="rounded border border-slate-800 bg-slate-950 px-2 py-1">
                      <span className="text-slate-500">[{new Date(entry.timestamp).toISOString().split("T")[1].slice(0, 8)}]</span>{" "}
                      <span className="text-amber-300">[{entry.source}]</span>{" "}
                      <span className="text-slate-300">{entry.message}</span>
                    </div>
                  ))
                )}
              </TabsContent>
            </Tabs>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="text-xs uppercase tracking-wider text-slate-400">Packing</div>
            <div className="mt-1 text-3xl font-semibold text-slate-100">{packingDensity}</div>
            <div className="text-xs text-slate-500">Live backend metric</div>
            <div className="mt-3 space-y-1 rounded-md border border-slate-800 bg-slate-950/60 p-2 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Last successful tick</span>
                <span className="font-mono text-slate-200">{lastTickTime}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Step latency</span>
                <span className="font-mono text-slate-200">
                  {backendHealth.lastStepLatencyMs !== null ? `${backendHealth.lastStepLatencyMs} ms` : "N/A"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Consecutive failures</span>
                <span className="font-mono text-slate-200">{backendHealth.consecutiveFailures}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Health probes (30s)</span>
                <span className="font-mono text-slate-200">{healthProbeCountWindow}</span>
              </div>
              <div className="text-slate-500">
                Reason: <span className="text-slate-300">{backendHealth.failureReason ?? "None"}</span>
              </div>
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
};

export default IntegratedDashboard;
