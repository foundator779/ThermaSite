import { useEffect, useMemo, useRef, useState } from 'react'
import { Bell, Check, ChevronRight, Music2, Radar, X } from 'lucide-react'
import type {
  MonitoringMission,
  MonitoringPolicyInput,
  MonitoringPolicyOptions,
  MonitoringSensitivity,
  MonitoringTriggerDirection,
  RunRecord,
} from '../../types/run'
import {
  cadenceLabel,
  defaultPolicy,
  hasCustomThresholds,
  policyFromMission,
  presetThresholds,
} from './policy'

const SENSITIVITY_OPTIONS: Array<[MonitoringSensitivity, string, string]> = [
  ['HIGH', 'High sensitivity', 'Earlier review'],
  ['BALANCED', 'Balanced', 'Recommended'],
  ['IMPORTANT_ONLY', 'Important only', 'Fewer incidents'],
]

const DIRECTION_OPTIONS: Array<[MonitoringTriggerDirection, string]> = [
  ['INCREASE', 'Increase'],
  ['DECREASE', 'Decrease'],
  ['EITHER', 'Either direction'],
]

export function MonitoringPolicyDrawer({ run, options, mission, initialPolicy, saving, error, onClose, onSave }: {
  run: RunRecord
  options: MonitoringPolicyOptions
  mission?: MonitoringMission
  initialPolicy?: MonitoringPolicyInput
  saving: boolean
  error?: Error | null
  onClose: () => void
  onSave: (policy: MonitoringPolicyInput) => void
}) {
  const startingPolicy = useMemo(
    () => mission ? policyFromMission(mission) : initialPolicy || defaultPolicy(run, options),
    [initialPolicy, mission, options, run],
  )
  const [name, setName] = useState(startingPolicy.name || '')
  const [objective, setObjective] = useState(startingPolicy.objective)
  const [cadence, setCadence] = useState(startingPolicy.cadence_days)
  const [customCadence, setCustomCadence] = useState(
    options.cadence_presets.some((item) => item.days === startingPolicy.cadence_days)
      ? 14
      : startingPolicy.cadence_days,
  )
  const [sensitivity, setSensitivity] = useState<MonitoringSensitivity>(startingPolicy.sensitivity)
  const [selected, setSelected] = useState<string[]>(startingPolicy.indicator_keys)
  const [thresholds, setThresholds] = useState<Record<string, number>>(startingPolicy.metric_thresholds)
  const [directions, setDirections] = useState<Record<string, MonitoringTriggerDirection>>(startingPolicy.trigger_directions)
  const [notifications, setNotifications] = useState(startingPolicy.notification_enabled)
  const [audioAlerts, setAudioAlerts] = useState(startingPolicy.audio_alert_enabled)
  const dialogRef = useRef<HTMLElement>(null)
  const customFrequency = !options.cadence_presets.some((item) => item.days === cadence)

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', closeOnEscape)
    dialogRef.current?.querySelector<HTMLElement>('input, button')?.focus()
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  const toggleIndicator = (key: string) => {
    const indicator = options.available_indicators.find((item) => item.key === key)
    if (!indicator) return
    if (selected.includes(key)) {
      setSelected((value) => value.filter((item) => item !== key))
      setThresholds((value) => Object.fromEntries(Object.entries(value).filter(([metric]) => metric !== indicator.metric)))
      setDirections((value) => Object.fromEntries(Object.entries(value).filter(([indicatorKey]) => indicatorKey !== key)) as Record<string, MonitoringTriggerDirection>)
      return
    }
    setSelected((value) => [...value, key])
    setThresholds((value) => ({ ...value, [indicator.metric]: indicator.thresholds[sensitivity] }))
    setDirections((value) => ({ ...value, [key]: indicator.default_direction }))
  }

  const changeSensitivity = (next: MonitoringSensitivity) => {
    if (next === sensitivity) return
    if (hasCustomThresholds(options, selected, sensitivity, thresholds)
      && !window.confirm('Changing sensitivity will replace your custom threshold values. Continue?')) return
    setSensitivity(next)
    setThresholds(presetThresholds(options, selected, next))
  }

  const submit = () => onSave({
    name: name.trim(),
    objective: objective.trim(),
    cadence_days: cadence,
    sensitivity,
    indicator_keys: selected,
    metric_thresholds: Object.fromEntries(
      options.available_indicators
        .filter((indicator) => selected.includes(indicator.key))
        .map((indicator) => [indicator.metric, thresholds[indicator.metric]]),
    ),
    trigger_directions: Object.fromEntries(
      selected.map((key) => [key, directions[key] || options.available_indicators.find((item) => item.key === key)?.default_direction || 'EITHER']),
    ),
    notification_enabled: notifications,
    audio_alert_enabled: audioAlerts,
  })

  const invalidThreshold = selected.some((key) => {
    const metric = options.available_indicators.find((item) => item.key === key)?.metric
    const value = metric ? thresholds[metric] : undefined
    return typeof value !== 'number' || !Number.isFinite(value) || value <= 0
  })
  const customized = hasCustomThresholds(options, selected, sensitivity, thresholds)

  return <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <aside ref={dialogRef} className="monitoring-drawer" role="dialog" aria-modal="true" aria-labelledby="monitoring-title">
      <header><div><span className="eyebrow">Monitoring policy</span><h2 id="monitoring-title">{mission ? 'Edit habitat watch' : 'Monitor this habitat'}</h2><p>Choose the evidence, schedule, and meaningful-change rules HabiWatch should evaluate autonomously.</p></div><button className="icon-button" onClick={onClose} aria-label="Close monitoring policy"><X size={19} /></button></header>

      <section className="policy-section"><label className="policy-label" htmlFor="policy-name">Policy name</label><input id="policy-name" value={name} maxLength={120} onChange={(event) => setName(event.target.value)} /></section>
      <section className="policy-section"><label className="policy-label" htmlFor="policy-objective">Monitoring objective</label><textarea id="policy-objective" value={objective} maxLength={500} rows={3} onChange={(event) => setObjective(event.target.value)} /></section>

      <section className="policy-section"><span className="policy-label">Frequency</span><div className="policy-frequency">{options.cadence_presets.map((preset) => <button key={preset.days} className={cadence === preset.days ? 'active' : ''} onClick={() => setCadence(preset.days)}><strong>{preset.label}</strong><span>{preset.days} {preset.days === 1 ? 'day' : 'days'}</span></button>)}<button className={customFrequency ? 'active' : ''} onClick={() => setCadence(customCadence)}><strong>Custom</strong><span>1–365 days</span></button></div>{customFrequency && <label className="custom-cadence">Check every <input aria-label="Custom monitoring frequency in days" type="number" min={1} max={365} value={customCadence} onChange={(event) => { const days = Number(event.target.value); setCustomCadence(days); setCadence(days) }} /> days</label>}<small>All selected indicators use this schedule. Each check requests the latest observations available from its source.</small></section>

      <section className="policy-section"><span className="policy-label">Sensitivity</span><div className="policy-segmented policy-segmented--three">{SENSITIVITY_OPTIONS.map(([value, label, detail]) => <button key={value} className={sensitivity === value ? 'active' : ''} onClick={() => changeSensitivity(value)}><strong>{label}</strong><span>{detail}</span></button>)}</div>{customized && <span className="custom-policy-badge">{sensitivity === 'IMPORTANT_ONLY' ? 'Important only' : sensitivity.charAt(0) + sensitivity.slice(1).toLowerCase()} + custom thresholds</span>}</section>

      <section className="policy-section"><span className="policy-label">What to monitor</span><div className="indicator-list">{options.available_indicators.map((indicator) => {
        const active = selected.includes(indicator.key)
        return <div key={indicator.key} className={`indicator-policy ${active ? 'active' : ''}`}>
          <label><input type="checkbox" checked={active} onChange={() => toggleIndicator(indicator.key)} /><span className="indicator-check">{active && <Check size={14} />}</span><span><strong>{indicator.label}</strong><small>{indicator.detail}</small></span></label>
          {active && <div className="indicator-policy__controls"><label>Alert at <span><input aria-label={`${indicator.label} threshold`} type="number" min={indicator.step} step={indicator.step} value={thresholds[indicator.metric] ?? indicator.thresholds[sensitivity]} onChange={(event) => setThresholds((value) => ({ ...value, [indicator.metric]: Number(event.target.value) }))} /> {indicator.unit}</span></label><label>When it <select aria-label={`${indicator.label} trigger direction`} value={directions[indicator.key] || indicator.default_direction} onChange={(event) => setDirections((value) => ({ ...value, [indicator.key]: event.target.value as MonitoringTriggerDirection }))}>{DIRECTION_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><small>Baseline value: {indicator.current_value.toLocaleString()} {indicator.unit}</small></div>}
        </div>
      })}</div><small>Species evidence is sampling-dependent. Scientific review must distinguish observation effort from a defensible habitat signal.</small></section>

      <section className="policy-section policy-notification"><Bell size={18} /><div><strong>Authorized notification</strong><span>Always create in-app incidents. Deliver validated incidents to the configured backend webhook.</span></div><label className="switch"><input aria-label="Send external notifications" type="checkbox" checked={notifications} onChange={(event) => setNotifications(event.target.checked)} /><span /></label></section>

      <section className="policy-section policy-notification"><Music2 size={18} /><div><strong>AI-generated incident audio</strong><span>Generate an opt-in 30-second Lyria Habitat Pulse for validated attention incidents. Operational audio—not scientific evidence.</span></div><label className="switch"><input aria-label="Generate AI incident audio" type="checkbox" checked={audioAlerts} onChange={(event) => setAudioAlerts(event.target.checked)} /><span /></label></section>

      <section className="policy-summary"><span className="policy-label">Policy summary</span><strong>{selected.length} indicator{selected.length === 1 ? '' : 's'} · {cadenceLabel(cadence)}</strong><p>An incident is created when any selected indicator crosses its threshold in the chosen direction.</p></section>
      <section className="policy-workflow"><span className="policy-label">Autonomous action</span><div><span>Acquire evidence</span><ChevronRight size={14} /><span>Gemma gate</span><ChevronRight size={14} /><span>Incident{audioAlerts ? ' + audio' : ''}</span></div></section>
      {error && <p className="drawer-error">{error.message}</p>}
      <footer><button className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={saving || selected.length === 0 || name.trim().length < 3 || objective.trim().length < 12 || cadence < 1 || cadence > 365 || invalidThreshold} onClick={submit}><Radar size={16} /> {saving ? 'Saving policy…' : mission ? 'Save policy' : 'Activate monitoring'}</button></footer>
    </aside>
  </div>
}
