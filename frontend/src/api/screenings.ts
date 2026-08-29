import { api } from './client'
import type { CoolingScenario, FacilityRequirements, FactorWeights, ResourceEstimate, ResourceEstimatorInput, ScreeningRecord, SiteCatalog } from '../types/screening'

export const DEFAULT_WEIGHTS: FactorWeights = {
  thermal: 40, power: 25, water: 15, permitting: 10, logistics: 10,
}

export const DEFAULT_COOLING: CoolingScenario = {
  it_load_mw: 50,
  utilization: 0.85,
  baseline_pue: 1.2,
  reference_temperature_c: 18,
  pue_sensitivity_per_c: 0.006,
  annualize: false,
}

export const DEFAULT_FACILITY: FacilityRequirements = {
  facility_size_acres: 40,
  it_density_mw_per_acre: 1.25,
  cooling_system: 'hybrid',
  shortlist_size: 5,
}

export async function getSiteCatalog() {
  return api<SiteCatalog>('/api/v1/site-catalog')
}

export async function createScreening(input: {
  brief: string
  facility: FacilityRequirements
  weights: FactorWeights
  cooling: CoolingScenario
}) {
  return api<{ screening_id: string; status: string }>('/api/v1/screenings', {
    method: 'POST',
    body: JSON.stringify({
      brief: input.brief,
      candidate_ids: [],
      candidates: [],
      auto_shortlist: true,
      facility: input.facility,
      weights: input.weights,
      cooling: input.cooling,
      constraints: { exclude_permitting_moratoria: true },
      thermal_window: {
        start_date: '2026-07-01', end_date: '2026-07-31', threshold_c: 35, granularity_m: 100,
      },
    }),
  })
}

export async function getScreening(screeningId: string) {
  return api<ScreeningRecord>(`/api/v1/screenings/${screeningId}`)
}

export async function listScreenings() {
  return api<ScreeningRecord[]>('/api/v1/screenings')
}

export async function rescoreScreening(screeningId: string, weights: FactorWeights) {
  return api<ScreeningRecord>(`/api/v1/screenings/${screeningId}/rescore`, {
    method: 'POST', body: JSON.stringify({ weights }),
  })
}

export async function estimateResources(screeningId: string, input: ResourceEstimatorInput) {
  return api<ResourceEstimate>(`/api/v1/screenings/${screeningId}/estimate`, {
    method: 'POST', body: JSON.stringify(input),
  })
}
