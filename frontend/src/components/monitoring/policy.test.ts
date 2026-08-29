import { describe, expect, it } from 'vitest'
import type { MonitoringPolicyOptions, RunRecord } from '../../types/run'
import { cadenceLabel, defaultPolicy, hasCustomThresholds, presetThresholds, validCadence } from './policy'

const options: MonitoringPolicyOptions = {
  run_id: 'run-1',
  available_indicators: [
    {
      key: 'wildfire_activity',
      label: 'Wildfire activity',
      detail: 'New detections',
      metric: 'recent_fire_detection_count',
      unit: 'detections',
      step: 1,
      current_value: 3,
      thresholds: { HIGH: 1, BALANCED: 1, IMPORTANT_ONLY: 2 },
      default_direction: 'INCREASE',
      recommended: true,
    },
    {
      key: 'wetland_inventory',
      label: 'Wetland inventory',
      detail: 'Mapped acreage',
      metric: 'nwi_mapped_wetland_acres',
      unit: 'acres',
      step: 0.1,
      current_value: 42,
      thresholds: { HIGH: 0.5, BALANCED: 2, IMPORTANT_ONLY: 5 },
      default_direction: 'DECREASE',
      recommended: true,
    },
  ],
  cadence_presets: [
    { label: 'Daily', days: 1 },
    { label: 'Weekly', days: 7 },
    { label: 'Monthly', days: 30 },
    { label: 'Quarterly', days: 90 },
  ],
  default_indicator_keys: ['wildfire_activity', 'wetland_inventory'],
  default_cadence_days: 30,
  default_sensitivity: 'BALANCED',
}

const run = {
  id: 'run-1',
  metrics: {},
  research_spec: { anchor_place: 'Selected area' },
} as unknown as RunRecord

describe('monitoring policy helpers', () => {
  it('builds a habitat-aware monthly policy with thresholds and directions', () => {
    const policy = defaultPolicy(run, options)

    expect(policy.cadence_days).toBe(30)
    expect(policy.metric_thresholds).toEqual({ recent_fire_detection_count: 1, nwi_mapped_wetland_acres: 2 })
    expect(policy.trigger_directions).toEqual({ wildfire_activity: 'INCREASE', wetland_inventory: 'DECREASE' })
  })

  it('detects custom thresholds and can replace them with another preset', () => {
    const selected = options.default_indicator_keys
    const balanced = presetThresholds(options, selected, 'BALANCED')
    expect(hasCustomThresholds(options, selected, 'BALANCED', balanced)).toBe(false)

    const customized = { ...balanced, nwi_mapped_wetland_acres: 3.5 }
    expect(hasCustomThresholds(options, selected, 'BALANCED', customized)).toBe(true)
    expect(presetThresholds(options, selected, 'HIGH')).toEqual({ recent_fire_detection_count: 1, nwi_mapped_wetland_acres: 0.5 })
  })

  it('formats presets and validates custom 1–365 day schedules', () => {
    expect(cadenceLabel(7)).toBe('Weekly')
    expect(cadenceLabel(17)).toBe('Every 17 days')
    expect(validCadence(1)).toBe(true)
    expect(validCadence(365)).toBe(true)
    expect(validCadence(0)).toBe(false)
    expect(validCadence(14.5)).toBe(false)
  })
})
