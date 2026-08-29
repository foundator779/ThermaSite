import type {
  MonitoringMission,
  MonitoringPolicyInput,
  MonitoringPolicyOptions,
  MonitoringSensitivity,
  RunRecord,
} from '../../types/run'

export const DEFAULT_OBJECTIVE = 'Notify me when authoritative evidence indicates a meaningful habitat change.'

export function defaultPolicy(run: RunRecord, options: MonitoringPolicyOptions): MonitoringPolicyInput {
  const sensitivity = options.default_sensitivity
  const selected = options.default_indicator_keys
  return {
    name: `${run.research_spec?.anchor_place || 'Selected habitat'} habitat watch`,
    objective: DEFAULT_OBJECTIVE,
    cadence_days: options.default_cadence_days,
    sensitivity,
    indicator_keys: selected,
    metric_thresholds: Object.fromEntries(
      options.available_indicators
        .filter((indicator) => selected.includes(indicator.key))
        .map((indicator) => [indicator.metric, indicator.thresholds[sensitivity]]),
    ),
    trigger_directions: Object.fromEntries(
      options.available_indicators
        .filter((indicator) => selected.includes(indicator.key))
        .map((indicator) => [indicator.key, indicator.default_direction]),
    ),
    notification_enabled: false,
    audio_alert_enabled: false,
  }
}

export function policyFromMission(mission: MonitoringMission): MonitoringPolicyInput {
  return {
    name: mission.name,
    objective: mission.objective,
    cadence_days: mission.cadence_days,
    sensitivity: mission.sensitivity,
    indicator_keys: mission.indicator_keys,
    metric_thresholds: mission.metric_thresholds,
    trigger_directions: mission.trigger_directions,
    notification_enabled: mission.notification_enabled,
    audio_alert_enabled: mission.audio_alert_enabled,
  }
}

export function presetThresholds(
  options: MonitoringPolicyOptions,
  selected: string[],
  sensitivity: MonitoringSensitivity,
) {
  return Object.fromEntries(
    options.available_indicators
      .filter((indicator) => selected.includes(indicator.key))
      .map((indicator) => [indicator.metric, indicator.thresholds[sensitivity]]),
  )
}

export function hasCustomThresholds(
  options: MonitoringPolicyOptions,
  selected: string[],
  sensitivity: MonitoringSensitivity,
  thresholds: Record<string, number>,
) {
  const preset = presetThresholds(options, selected, sensitivity)
  return Object.entries(preset).some(([metric, value]) => Math.abs((thresholds[metric] ?? value) - value) > 1e-9)
}

export function cadenceLabel(days: number) {
  return ({ 1: 'Daily', 7: 'Weekly', 30: 'Monthly', 90: 'Quarterly' } as Record<number, string>)[days] || `Every ${days} days`
}

export function validCadence(days: number) {
  return Number.isInteger(days) && days >= 1 && days <= 365
}
