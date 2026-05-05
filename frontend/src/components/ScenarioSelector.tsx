import React, { useEffect, useState, useCallback } from 'react';
import { useSimulationStore } from '@/simulation/store';

const API_BASE = 'http://127.0.0.1:8000/api';

interface ScenarioFleet {
  small: number;
  large: number;
  preferred_model?: string;
}

interface AHSScenario {
  id: string;
  name: string;
  description: string;
  polygon: { x: number; y: number }[];
  entry_point: { x: number; y: number };
  fleet: ScenarioFleet;
  scenario: {
    material_type: string;
    weather: { rain_intensity: number; wind_speed: number; wind_direction_deg: number; visibility_m: number };
    timeline: { time_sec: number; property_path: string; value: number }[];
  };
}

const SCENARIO_ICONS: Record<string, string> = {
  S01: 'RAIN', S02: 'FLAT', S03: 'CHOKE', S03A: 'CHOKE', S03B: 'DYN', S04: 'COLD',
  S05: 'MIX', S06: 'GPS', S07: 'DENSE', S08: 'NIGHT',
};

const SCENARIO_BADGE_COLORS: Record<string, string> = {
  S01: '#EF4444', S02: '#22C55E', S03: '#F97316', S03A: '#F97316', S03B: '#FB7185', S04: '#3B82F6',
  S05: '#8B5CF6', S06: '#EAB308', S07: '#14B8A6', S08: '#6366F1',
};

const ScenarioSelector: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [scenarios, setScenarios] = useState<AHSScenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { setFleetCounts, init, addLogMessage } = useSimulationStore();

  useEffect(() => {
    fetch(`${API_BASE}/scenarios`)
      .then(r => r.json())
      .then(data => {
        setScenarios(data.scenarios || []);
        setLoading(false);
      })
      .catch(e => {
        setError('Failed to load scenarios from backend.');
        setLoading(false);
      });
  }, []);

  const applyScenario = useCallback(async (s: AHSScenario) => {
    setApplying(s.id);
    try {
      // 1. Tell backend to load & reset with this scenario
      await fetch(`${API_BASE}/load_scenario/${s.id}`, { method: 'POST' });

      // 2. Push polygon and entry point into init_yard so the frontend redraws
      const initRes = await fetch(`${API_BASE}/init_yard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygon: s.polygon,
          entry_point: s.entry_point,
          scenario: s.scenario,
        }),
      });
      if (!initRes.ok) throw new Error('init_yard failed');

      // 3. Update fleet counts in the store to trigger truck re-creation
      await setFleetCounts({ small: s.fleet.small, large: s.fleet.large });

      addLogMessage('MQTT', `Scenario ${s.id} loaded: ${s.name}`);
      onClose();
    } catch (e) {
      setError(`Failed to apply scenario ${s.id}.`);
    } finally {
      setApplying(null);
    }
  }, [setFleetCounts, addLogMessage, onClose]);

  const getWeatherLabel = (s: AHSScenario) => {
    const { rain_intensity, wind_speed } = s.scenario.weather;
    if (rain_intensity > 20) return '⛈ Heavy Rain';
    if (rain_intensity > 5) return '🌦 Light Rain';
    if (wind_speed > 35) return '💨 High Wind';
    return '☀ Clear';
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.70)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        background: 'hsl(222 47% 11%)',
        border: '1px solid hsl(217 33% 22%)',
        borderRadius: '16px',
        width: '760px',
        maxHeight: '85vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 24px 80px rgba(0,0,0,0.6)',
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid hsl(217 33% 22%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: '#F1F5F9', letterSpacing: '0.02em' }}>
              AHS Verified Scenarios
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#94A3B8' }}>
              8 pre-configured test scenarios with fleet, polygon, weather, and timeline events
            </p>
          </div>
          <button
            onClick={onClose}
            id="scenario-selector-close"
            style={{
              background: 'none', border: '1px solid hsl(217 33% 28%)',
              borderRadius: '8px', color: '#94A3B8',
              width: 32, height: 32, cursor: 'pointer', fontSize: '16px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          {loading && (
            <div style={{ gridColumn: '1/-1', textAlign: 'center', color: '#94A3B8', padding: '40px' }}>
              Loading scenarios…
            </div>
          )}
          {error && (
            <div style={{ gridColumn: '1/-1', textAlign: 'center', color: '#EF4444', padding: '20px', fontSize: '13px' }}>
              {error}
            </div>
          )}
          {scenarios.map(s => {
            const isApplying = applying === s.id;
            const badgeColor = SCENARIO_BADGE_COLORS[s.id] || '#64748B';
            const hasTimeline = s.scenario.timeline && s.scenario.timeline.length > 0;
            return (
              <div
                key={s.id}
                id={`scenario-card-${s.id}`}
                style={{
                  background: 'hsl(222 47% 14%)',
                  border: `1px solid hsl(217 33% 22%)`,
                  borderRadius: '12px',
                  padding: '16px',
                  cursor: isApplying ? 'wait' : 'pointer',
                  transition: 'border-color 0.15s, box-shadow 0.15s',
                  opacity: isApplying ? 0.7 : 1,
                }}
                onMouseEnter={e => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = badgeColor;
                  (e.currentTarget as HTMLDivElement).style.boxShadow = `0 0 0 1px ${badgeColor}40`;
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = 'hsl(217 33% 22%)';
                  (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', marginBottom: '10px' }}>
                  <span style={{ fontSize: '22px', lineHeight: 1 }}>{SCENARIO_ICONS[s.id] || '🗂️'}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                      <span style={{
                        fontSize: '10px', fontWeight: 700, letterSpacing: '0.08em',
                        color: badgeColor, background: `${badgeColor}20`,
                        borderRadius: '4px', padding: '1px 6px',
                      }}>{s.id}</span>
                      {hasTimeline && (
                        <span style={{
                          fontSize: '10px', fontWeight: 600, color: '#F97316',
                          background: '#F9731620', borderRadius: '4px', padding: '1px 6px',
                        }}>⏱ TIMELINE</span>
                      )}
                    </div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: '#F1F5F9', marginTop: '4px', lineHeight: 1.3 }}>
                      {s.name.replace(/^S0\d[A-Z]?\s[–-]\s/, '')}
                    </div>
                  </div>
                </div>

                <p style={{ fontSize: '11px', color: '#94A3B8', margin: '0 0 10px', lineHeight: 1.5 }}>
                  {s.description.length > 100 ? s.description.slice(0, 100) + '…' : s.description}
                </p>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px', marginBottom: '12px' }}>
                  <span style={pillStyle}>{getWeatherLabel(s)}</span>
                  <span style={pillStyle}>🚛 {s.fleet.small + s.fleet.large} trucks</span>
                  <span style={pillStyle}>📦 {s.scenario.material_type}</span>
                  {hasTimeline && (
                    <span style={{ ...pillStyle, color: '#F97316', borderColor: '#F9731640' }}>
                      ⏱ T={s.scenario.timeline[0].time_sec}s
                    </span>
                  )}
                </div>

                <button
                  id={`scenario-load-${s.id}`}
                  onClick={() => applyScenario(s)}
                  disabled={!!applying}
                  style={{
                    width: '100%', padding: '8px',
                    background: isApplying ? '#334155' : badgeColor + '22',
                    border: `1px solid ${badgeColor}55`,
                    borderRadius: '8px',
                    color: isApplying ? '#94A3B8' : badgeColor,
                    fontSize: '12px', fontWeight: 700,
                    cursor: applying ? 'not-allowed' : 'pointer',
                    transition: 'background 0.15s',
                    letterSpacing: '0.05em',
                  }}
                >
                  {isApplying ? 'Applying…' : '▶ Load Scenario'}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const pillStyle: React.CSSProperties = {
  fontSize: '10px',
  color: '#CBD5E1',
  background: 'hsl(217 33% 18%)',
  border: '1px solid hsl(217 33% 28%)',
  borderRadius: '4px',
  padding: '2px 7px',
  whiteSpace: 'nowrap',
};

export default ScenarioSelector;

