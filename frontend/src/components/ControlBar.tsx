import React, { useState } from 'react';
import { useSimulationStore } from '@/simulation/store';
import { Play, Pause, RotateCcw, Eye, Edit3, CheckCircle, MapPin, FlaskConical } from 'lucide-react';
import ScenarioSelector from './ScenarioSelector';

const ControlBar: React.FC = () => {
  const [showScenarios, setShowScenarios] = useState(false);
  const { 
    running, speed, viewMode, showHeatmap, start, pause, reset, setSpeed, setViewMode, toggleHeatmap,
    isDrawing, settingEntryPoint, startDrawingMode, finishPolygon, polygonVertices, setEntryPointMode, yardPolygon
  } = useSimulationStore();

  return (
    <>
      {showScenarios && <ScenarioSelector onClose={() => setShowScenarios(false)} />}
    <div className="control-bar justify-between">
      <div className="flex items-center gap-2">
        <span className="font-mono-data text-xs text-muted-foreground tracking-widest mr-2">ADPS</span>
        <div className="h-4 w-px bg-border" />

        <button
          id="scenario-selector-trigger"
          onClick={() => setShowScenarios(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:bg-muted transition-colors"
        >
          <FlaskConical size={12} /> AHS Scenarios
        </button>

        <div className="h-4 w-px bg-border" />

        {!running ? (
          <button
            onClick={start}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-accent text-accent-foreground text-xs font-semibold hover:opacity-90 transition-opacity"
          >
            <Play size={12} /> Start
          </button>
        ) : (
          <button
            onClick={pause}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-semibold hover:opacity-90 transition-opacity"
          >
            <Pause size={12} /> Pause
          </button>
        )}

        <button
          onClick={reset}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:bg-muted transition-colors"
        >
          <RotateCcw size={12} /> Reset
        </button>

        <button
          onClick={startDrawingMode}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-xs font-medium transition-colors ${
            isDrawing || settingEntryPoint ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:bg-muted'
          }`}
        >
          <Edit3 size={12} /> Draw Yard
        </button>

        {isDrawing && (
          <button
            onClick={finishPolygon}
            disabled={polygonVertices.length < 3}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-xs font-medium transition-colors ${
              polygonVertices.length >= 3 ? 'bg-accent text-accent-foreground border-accent hover:opacity-90' : 'bg-muted text-muted-foreground border-border opacity-50 cursor-not-allowed'
            }`}
          >
            <CheckCircle size={12} /> Finish Polygon
          </button>
        )}
        
        {yardPolygon.length >= 3 && !isDrawing && (
          <button
            onClick={setEntryPointMode}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-xs font-medium transition-colors ${
              settingEntryPoint ? 'bg-accent text-accent-foreground border-accent' : 'border-border text-muted-foreground hover:bg-muted'
            }`}
          >
            <MapPin size={12} /> Move Entry Point
          </button>
        )}

        <div className="h-4 w-px bg-border" />

        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground font-medium">Speed</span>
          <input
            type="range"
            min={0.5}
            max={5}
            step={0.5}
            value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))}
            className="w-20 h-1 accent-accent"
          />
          <span className="font-mono-data text-xs text-foreground w-6">{speed}x</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={toggleHeatmap}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-xs font-medium transition-colors ${
            showHeatmap ? 'bg-accent text-accent-foreground border-accent' : 'border-border text-muted-foreground hover:bg-muted'
          }`}
        >
          <Eye size={12} /> Heatmap
        </button>

        <div className="h-4 w-px bg-border" />

        <div className="flex rounded-md border border-border overflow-hidden">
          <button
            onClick={() => setViewMode('2d')}
            className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
              viewMode === '2d' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'
            }`}
          >
            2D
          </button>
          <button
            onClick={() => setViewMode('3d')}
            className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
              viewMode === '3d' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'
            }`}
          >
            3D
          </button>
        </div>
      </div>
    </div>
    </>
  );
};

export default ControlBar;
