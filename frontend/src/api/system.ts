import { api } from './client'

export interface ReadinessResponse {
  status: 'ready' | 'configuration_required'
  environment: string
  checks: {
    gemini: {
      configured: boolean
      model: string
      provider: string
      sdk: string
      agent_framework: string
    }
    fortyguard: {
      configured: boolean
      provider: string
      authentication: string
      aoi_limit_sq_mi: number
    }
    grounded_research: { configured: boolean; provider: string; cache_ttl_days: number }
    persistence: string
    authentication: { configured: boolean; sessions: string; demo_account: boolean }
    artifact_storage: string
  }
}

export async function getReadiness() {
  return api<ReadinessResponse>('/api/v1/readyz')
}
