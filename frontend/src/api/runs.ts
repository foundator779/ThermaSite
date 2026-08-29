import { api } from './client'
import type { BriefingVideoStatus, ModelUsageRecord, RunRecord, RunSummary, StudyArea, VegetationSample } from '../types/run'

export async function createRun({ query, studyArea, demoFault = false }: { query: string; studyArea: StudyArea; demoFault?: boolean }) {
  return api<{ run_id: string; status: string }>('/api/v1/runs', {
    method: 'POST', body: JSON.stringify({ query, study_area: studyArea, demo_fault: demoFault }),
  })
}

export async function getRun(runId: string) {
  return api<RunRecord>(`/api/v1/runs/${runId}`)
}

export async function listRuns() {
  return api<RunSummary[]>('/api/v1/runs')
}

export async function cancelRun(runId: string) {
  return api(`/api/v1/runs/${runId}/cancel`, { method: 'POST' })
}

export async function generateBriefingVideo(runId: string) {
  return api<{ run_id: string; status: BriefingVideoStatus; model: string }>(`/api/v1/runs/${runId}/briefing-video`, {
    method: 'POST',
  })
}

export async function getVegetationSample(runId: string, latitude: number, longitude: number) {
  const params = new URLSearchParams({ latitude: String(latitude), longitude: String(longitude) })
  return api<VegetationSample>(`/api/v1/runs/${runId}/vegetation/sample?${params}`)
}

export async function getModelUsage(runId: string) {
  return api<{ run_id: string; models: ModelUsageRecord[] }>(`/api/v1/runs/${runId}/model-usage`)
}
