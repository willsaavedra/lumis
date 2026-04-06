import type { AgentStateType } from './state.js';

export function routeAfterClone(state: AgentStateType): string {
  return state.request.analysisType === 'context' ? 'contextDiscovery' : 'preTriage';
}

export function routeAfterConsolidate(state: AgentStateType): string {
  return state.request.analysisType === 'quick' ? 'deduplicate' : 'analyzeEfficiency';
}
