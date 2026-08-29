export type RunStatus =
  | 'CREATED' | 'INTERPRETING' | 'DISCOVERING_DATA' | 'SELECTING_DATASETS'
  | 'ACQUIRING_DATA' | 'VALIDATING_DATA' | 'HARMONIZING_DATA' | 'PLANNING_ANALYSIS'
  | 'GENERATING_CODE' | 'EXECUTING' | 'REPAIRING' | 'VALIDATING_OUTPUT'
  | 'GENERATING_REPORT' | 'PACKAGING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export type BriefingVideoStatus = 'NOT_REQUESTED' | 'QUEUED' | 'GENERATING' | 'COMPLETED' | 'FAILED'

export interface StudyArea {
  shape: 'circle' | 'polygon'
  geometry: GeoJSON.Polygon
  center: [number, number]
  bbox: [number, number, number, number]
  area_sq_mi: number
  radius_miles?: number
  label?: string
}

export interface DatasetCandidate {
  dataset_id: string
  name: string
  provider: string
  match_score: number
  rationale: string
  data_role: string
  spatial_resolution: string
  temporal_resolution?: string
  documentation_url?: string
  footprint?: GeoJSON.Geometry
}

export interface RunEvent {
  id: string
  timestamp: string
  agent: string
  type: string
  message: string
  status: 'pending' | 'active' | 'success' | 'warning' | 'error'
  payload: Record<string, unknown>
}

export interface Artifact {
  id: string
  type: string
  name: string
  uri: string
  sha256: string
  content_type: string
  size_bytes: number
  created_by: string
  download_url?: string
}

export interface RasterLegendStop {
  value: number
  label: string
  color: string
}

export interface MapRasterLayer {
  id: string
  label: string
  metric: 'ndvi' | 'ndmi' | 'stress'
  period: 'current' | 'baseline' | 'anomaly'
  artifact_id: string
  bounds: [number, number, number, number]
  unit: string
  legend: RasterLegendStop[]
  opacity: number
  resolution_m: number
  scientific_resolution_m: number
  display_width_px?: number
  display_height_px?: number
  download_url?: string
}

export interface VegetationAnalysis {
  status: 'available' | 'insufficient'
  source: string
  attribution: string
  resolution_m: number
  current_period: { start: string; end: string }
  baseline_period: { start: string; end: string }
  current_scene_count: number
  baseline_scene_count: number
  valid_coverage_pct: number
  observation_age_days?: number
  latest_observation_date?: string
  median_ndvi?: number
  baseline_median_ndvi?: number
  ndvi_anomaly?: number
  median_ndmi?: number
  baseline_median_ndmi?: number
  ndmi_anomaly?: number
  stressed_area_pct?: number
  stressed_area_sq_mi?: number
  confidence: number
  scene_ids: string[]
  layers: MapRasterLayer[]
  sample_grid_artifact_id?: string
  warnings: string[]
}

export interface VegetationSample {
  latitude: number
  longitude: number
  current_ndvi?: number
  baseline_ndvi?: number
  current_ndmi?: number
  baseline_ndmi?: number
  seasonal_percentile?: number
  classification: string
}

export interface ChartSeries {
  key: string
  label: string
  color: string
  kind?: 'line' | 'bar'
}

export interface ChartDefinition {
  kind: 'line' | 'bar' | 'composed' | 'scatter'
  data: Array<Record<string, string | number | null>>
  x_key: string
  y_key?: string
  x_label?: string
  y_label?: string
  unit?: string
  series: ChartSeries[]
}

export interface RunRecord {
  id: string
  status: RunStatus
  created_at: string
  updated_at: string
  user_query: string
  current_step: string
  progress: number
  research_spec?: {
    anchor_place: string
    region: string
    start_date: string
    end_date: string
    required_data_roles: string[]
    causal_claim_allowed: boolean
    habitat_type: string
    research_geometry?: GeoJSON.Geometry
  }
  selected_datasets: DatasetCandidate[]
  events: RunEvent[]
  metrics: Record<string, number | string>
  chart_data?: Record<string, ChartDefinition>
  final_summary?: string
  harmonization?: {
    overlap_start: string
    overlap_end: string
    paired_sample_count: number
    temporal_aggregation: string
  }
  artifacts: Artifact[]
  error?: { code: string; message: string }
  monitoring_mission_id?: string
  monitoring_baseline_run_id?: string
  confidence?: number
  evidence_disagreements: Array<{ indicator: string; severity: string; message: string; value?: number }>
  operational_impact: Record<string, number | string>
  study_area?: StudyArea
  briefing_video_status: BriefingVideoStatus
  briefing_video_error?: string
  briefing_video_artifact_id?: string
  briefing_video_model?: string
  vegetation?: VegetationAnalysis
}

export interface RunSummary {
  id: string
  status: RunStatus
  created_at: string
  updated_at: string
  user_query: string
  current_step: string
  progress: number
  selected_dataset_count: number
  artifact_count: number
  final_summary?: string
  error?: { code: string; message: string }
  monitoring_mission_id?: string
}

export interface MetricComparison {
  metric: string
  previous_value: number
  current_value: number
  absolute_delta: number
  threshold: number
  direction: MonitoringTriggerDirection
  meaningful: boolean
}

export interface MissionCheck {
  run_id: string
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  started_at: string
  completed_at?: string
  meaningful_change?: boolean
  comparisons: MetricComparison[]
  summary?: string
  error?: string
}

export interface MonitoringAlert {
  id: string
  created_at: string
  severity: 'info' | 'attention'
  title: string
  message: string
  run_id: string
  metric?: string
  comparison_metrics: string[]
  field_actions: string[]
  field_tasks: Array<{
    id: string
    title: string
    instructions: string
    priority: 'routine' | 'priority' | 'urgent'
    coordinates?: [number, number]
    status: 'prepared' | 'dispatched' | 'completed'
  }>
  action_packet_artifact_id?: string
  audio_status: 'NOT_REQUESTED' | 'QUEUED' | 'GENERATING' | 'COMPLETED' | 'FAILED'
  audio_job_id?: string
  audio_artifact_id?: string
  audio_model?: string
  audio_error?: string
  acknowledged: boolean
  delivery?: Record<string, unknown>
}

export type MonitoringSensitivity = 'HIGH' | 'BALANCED' | 'IMPORTANT_ONLY'
export type MonitoringTriggerDirection = 'INCREASE' | 'DECREASE' | 'EITHER'

export interface MonitoringMission {
  id: string
  name: string
  status: 'ACTIVE' | 'PAUSED'
  created_at: string
  updated_at: string
  baseline_run_id: string
  latest_run_id: string
  query: string
  region: string
  habitat: string
  objective: string
  cadence_days: number
  sensitivity: MonitoringSensitivity
  indicator_keys: string[]
  next_check_at: string
  metric_thresholds: Record<string, number>
  trigger_directions: Record<string, MonitoringTriggerDirection>
  run_ids: string[]
  checks: MissionCheck[]
  alerts: MonitoringAlert[]
  notification_enabled: boolean
  audio_alert_enabled: boolean
}

export interface MonitoringPolicyInput {
  name?: string
  objective: string
  cadence_days: number
  sensitivity: MonitoringSensitivity
  indicator_keys: string[]
  metric_thresholds: Record<string, number>
  trigger_directions: Record<string, MonitoringTriggerDirection>
  notification_enabled: boolean
  audio_alert_enabled: boolean
}

export interface ModelUsageRecord {
  family: 'Gemini' | 'Gemma' | 'Veo' | 'Lyria'
  model: string
  purpose: string
  status: 'configured' | 'completed' | 'failed' | 'queued' | 'generating'
  invocation_count: number
  last_used_at?: string
  artifact_ids: string[]
}

export interface MonitoringCadencePreset {
  label: string
  days: number
}

export interface MonitoringIndicatorOption {
  key: string
  label: string
  detail: string
  metric: string
  unit: string
  step: number
  current_value: number
  thresholds: Record<MonitoringSensitivity, number>
  default_direction: MonitoringTriggerDirection
  recommended: boolean
}

export interface MonitoringPolicyOptions {
  run_id: string
  available_indicators: MonitoringIndicatorOption[]
  cadence_presets: MonitoringCadencePreset[]
  default_indicator_keys: string[]
  default_cadence_days: number
  default_sensitivity: MonitoringSensitivity
}

export interface EvidenceNode {
  id: string
  kind: 'claim' | 'metric' | 'dataset' | 'transformation' | 'code' | 'validation' | 'artifact'
  label: string
  detail: string
  uri?: string
  sha256?: string
}

export interface EvidenceLink {
  source: string
  target: string
  relationship: string
}

export interface EvidenceChain {
  run_id: string
  claim: string
  nodes: EvidenceNode[]
  links: EvidenceLink[]
  validation_status: 'validated' | 'incomplete'
}

export interface RegistryDataset {
  dataset_id: string
  name: string
  provider: string
  data_role: string
  authority_score: number
  temporal_resolution: string
  spatial_resolution: string
  documentation_url: string
  rationale: string
  footprint?: GeoJSON.Geometry
}

export interface DatasetRegistry {
  registry_version: string
  datasets: RegistryDataset[]
}
