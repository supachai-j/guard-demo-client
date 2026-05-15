import React, { useEffect, useState } from 'react';
import { apiService } from '../services/api';
import { ScenarioPreview } from '../types';

interface ScenarioSwitcherProps {
  activeBusinessName?: string;
  onApplied: () => void;
}

const ScenarioSwitcher: React.FC<ScenarioSwitcherProps> = ({ activeBusinessName, onApplied }) => {
  const [scenarios, setScenarios] = useState<ScenarioPreview[]>([]);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiService
      .listScenarios()
      .then(({ scenarios }) => setScenarios(scenarios))
      .catch((e) => setError(e?.message || 'Failed to load scenarios'));
  }, []);

  if (error) {
    return <div className="text-sm text-red-600">Could not load demo scenarios: {error}</div>;
  }

  if (scenarios.length === 0) {
    return null;
  }

  const handleClick = async (scenarioId: string) => {
    setApplyingId(scenarioId);
    setError(null);
    try {
      await apiService.applyScenario(scenarioId);
      await onApplied();
    } catch (e: any) {
      setError(e?.message || 'Failed to apply scenario');
    } finally {
      setApplyingId(null);
    }
  };

  return (
    <div className="bg-white/80 backdrop-blur border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs font-medium uppercase tracking-wider text-gray-500 mr-1">
            Demo company
          </span>
          {scenarios.map((scenario) => {
            const isActive = activeBusinessName === scenario.business_name;
            const isApplying = applyingId === scenario.id;
            return (
              <button
                key={scenario.id}
                onClick={() => handleClick(scenario.id)}
                disabled={applyingId !== null}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm transition-all
                  ${isActive
                    ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-200'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-gray-400 hover:bg-gray-50'}
                  ${applyingId && !isApplying ? 'opacity-50 cursor-not-allowed' : ''}
                  ${isApplying ? 'opacity-70 cursor-wait' : ''}`}
                title={`${scenario.business_name} — ${scenario.industry}`}
              >
                <img
                  src={scenario.logo_url}
                  alt={`${scenario.business_name} logo`}
                  className="h-5 w-5 object-contain"
                />
                <span className="font-medium">{scenario.business_name}</span>
                <span className="text-xs text-gray-500">{scenario.industry}</span>
                {isApplying && (
                  <span className="ml-1 inline-block h-3 w-3 rounded-full border-2 border-primary-300 border-t-primary-600 animate-spin" />
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default ScenarioSwitcher;
