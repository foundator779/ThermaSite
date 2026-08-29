export type ScreeningStatus =
  | 'CREATED' | 'PLANNING' | 'ACQUIRING_HEAT' | 'RESEARCHING_SITES'
  | 'SCORING' | 'AUDITING' | 'REPORTING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export interface SourceCitation {
  title: string
  url: string
  publisher: string
  retrieved_at: string
  fact: string
  official: boolean
}

export interface SiteEvidence {
  summary: string
  permitting_readiness: 'explicit_by_right' | 'administrative_or_special_review' | 'discretionary_multi_agency' | 'moratorium_or_prohibition' | 'unknown'
  infrastructure_readiness: 'established' | 'documented' | 'limited' | 'unknown'
  industrial_energy_price_cents_kwh?: number
  facts: Array<{ category: 'power' | 'water' | 'permitting' | 'logistics'; fact: string; source_url: string; confidence: number }>
  validation_warnings: string[]
}

export interface FactorWeights {
  thermal: number
  power: number
  water: number
  permitting: number
  logistics: number
}

export interface CoolingScenario {
  it_load_mw: number
  utilization: number
  baseline_pue: number
  reference_temperature_c: number
  pue_sensitivity_per_c: number
  annualize: boolean
}

export interface FacilityRequirements {
  facility_size_acres: number
  it_density_mw_per_acre: number
  cooling_system: CoolingSystem
  shortlist_size: 5
}

export type CoolingSystem = 'dry' | 'evaporative' | 'hybrid' | 'liquid'

export interface ResourceEstimatorInput {
  site_id: string
  polygon: GeoJSON.FeatureCollection
  it_load_mw: number
  utilization: number
  baseline_pue: number
  reference_temperature_c: number
  pue_sensitivity_per_c: number
  cooling_system: CoolingSystem
  it_density_mw_per_acre?: number
}

export interface ResourceEstimate {
  id: string
  site_id: string
  created_at: string
  polygon: GeoJSON.FeatureCollection
  area_acres: number
  area_sq_mi: number
  cooling_system: CoolingSystem
  it_density_mw_per_acre?: number
  it_load_mw: number
  utilization: number
  baseline_pue: number
  heat_adjusted_pue: number
  peak_pue: number
  average_facility_power_mw: number
  peak_facility_power_mw: number
  window_it_energy_mwh: number
  window_facility_energy_mwh: number
  window_water_liters_low: number
  window_water_liters_high: number
  window_water_gallons_low: number
  window_water_gallons_high: number
  illustrative_annual_energy_mwh: number
  illustrative_annual_water_gallons_low: number
  illustrative_annual_water_gallons_high: number
  wue_l_kwh_low: number
  wue_l_kwh_high: number
  thermal: ThermalMetrics
  confidence: number
  assumptions: string[]
  disclaimer: string
}

export interface CandidateInput {
  name: string
  metro: string
  state: string
  latitude: number
  longitude: number
  area_sq_mi: number
}

export interface ThermalMetrics {
  activity_ids: string[]
  mean_temperature_c: number
  maximum_temperature_c: number
  minimum_temperature_c?: number
  exceedance_ratio: number
  threshold_c: number
  map_data: GeoJSON.FeatureCollection
  source: string
}

export interface CandidateSite {
  id: string
  name: string
  metro: string
  state: string
  latitude: number
  longitude: number
  area_sq_mi: number
  catalog: boolean
  industrial_energy_price_cents_kwh?: number
  water_risk_0_5?: number
  permitting_score?: number
  logistics_score?: number
  permitting_status: string
  citations: SourceCitation[]
  research_summary?: string
  evidence?: SiteEvidence
  thermal?: ThermalMetrics
  warnings: string[]
  shortlist_reason?: string
}

export interface FactorScore {
  factor: keyof FactorWeights
  score: number
  confidence: number
  weight: number
  contribution: number
  detail: string
}

export interface SiteRecommendation {
  site_id: string
  rank?: number
  score?: number
  decision_readiness: number
  rankable: boolean
  eligible: boolean
  constraint_failures: string[]
  factor_scores: FactorScore[]
  cooling_burden_index?: number
  selected_window_cooling_cost_usd?: number
  illustrative_annual_cooling_cost_usd?: number
}

export interface ScreeningEvent {
  id: string
  timestamp: string
  agent: string
  type: string
  message: string
  status: 'pending' | 'active' | 'success' | 'warning' | 'error'
  payload: Record<string, unknown>
}

export interface ScreeningRecord {
  id: string
  status: ScreeningStatus
  created_at: string
  updated_at: string
  request: {
    brief: string
    candidate_ids: string[]
    candidates: CandidateInput[]
    auto_shortlist: boolean
    facility: FacilityRequirements
    weights: FactorWeights
    constraints: {
      max_energy_price_cents_kwh?: number
      max_water_risk?: number
      exclude_permitting_moratoria: boolean
    }
    cooling: CoolingScenario
    thermal_window: {
      start_date: string
      end_date: string
      threshold_c: number
      granularity_m: number
    }
  }
  candidates: CandidateSite[]
  recommendations: SiteRecommendation[]
  resource_estimates: ResourceEstimate[]
  events: ScreeningEvent[]
  progress: number
  current_step: string
  summary?: string
  due_diligence: string[]
  artifacts: Array<{ id: string; name: string; content_type: string; size_bytes: number }>
  audit?: { passed: boolean; warnings: string[]; summary: string }
  error?: { code: string; message: string; retryable: boolean }
}

export interface SiteCatalog {
  version: string
  sites: CandidateSite[]
}
