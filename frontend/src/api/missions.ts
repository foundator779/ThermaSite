import { api } from './client'
import type { EvidenceChain, MonitoringAlert, MonitoringMission, MonitoringPolicyInput, MonitoringPolicyOptions } from '../types/run'

export async function getEvidence(runId: string) {
  return api<EvidenceChain>(`/api/v1/runs/${runId}/evidence`)
}

export async function getMonitoringPolicyOptions(runId: string) {
  return api<MonitoringPolicyOptions>(`/api/v1/runs/${runId}/monitoring-policy/options`)
}

export async function createMission(runId: string, policy: MonitoringPolicyInput) {
  return api<{ mission_id: string; status: string }>('/api/v1/missions', {
    method: 'POST',
    body: JSON.stringify({ source_run_id: runId, ...policy }),
  })
}

export async function getMission(missionId: string) {
  return api<MonitoringMission>(`/api/v1/missions/${missionId}`)
}

export async function listMissions() {
  return api<MonitoringMission[]>('/api/v1/missions')
}

export async function checkMission(missionId: string) {
  return api<{ run_id: string; status: string }>(`/api/v1/missions/${missionId}/check`, {
    method: 'POST',
  })
}

export async function updateMission(missionId: string, policy: Partial<MonitoringPolicyInput> & { status?: 'ACTIVE' | 'PAUSED' }) {
  return api<MonitoringMission>(`/api/v1/missions/${missionId}`, {
    method: 'PATCH',
    body: JSON.stringify(policy),
  })
}

export async function retryAlertDelivery(missionId: string, alertId: string) {
  return api<MonitoringAlert>(`/api/v1/missions/${missionId}/alerts/${alertId}/retry-delivery`, {
    method: 'POST',
  })
}

export async function retryAlertAudio(missionId: string, alertId: string) {
  return api<MonitoringAlert>(`/api/v1/missions/${missionId}/alerts/${alertId}/audio/retry`, {
    method: 'POST',
  })
}
