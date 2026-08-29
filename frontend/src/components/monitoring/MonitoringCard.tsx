import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, BellRing, CalendarClock, Check, ClipboardCheck, Download, LoaderCircle, LockKeyhole, Music2, Pause, Play, Radar, RefreshCw, Settings2 } from 'lucide-react'
import { artifactUrl } from '../../api/client'
import { checkMission, createMission, getMission, getMonitoringPolicyOptions, retryAlertAudio, retryAlertDelivery, updateMission } from '../../api/missions'
import type { MonitoringPolicyInput, RunRecord } from '../../types/run'
import { MonitoringPolicyDrawer } from './MonitoringPolicyDrawer'
import { cadenceLabel, defaultPolicy, hasCustomThresholds } from './policy'

export function MonitoringCard({ run, onOpenRun }: { run?: RunRecord; onOpenRun?: (runId: string) => void }) {
  const queryClient = useQueryClient()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [createdMissionId, setCreatedMissionId] = useState<string>()
  const [quickPolicy, setQuickPolicy] = useState<MonitoringPolicyInput>()
  const [customCadence, setCustomCadence] = useState(14)
  const initializedRun = useRef<string | undefined>(undefined)
  const missionId = run?.monitoring_mission_id || createdMissionId
  const options = useQuery({
    queryKey: ['monitoring-options', run?.id],
    queryFn: () => getMonitoringPolicyOptions(run!.id),
    enabled: run?.status === 'COMPLETED',
  })
  const mission = useQuery({
    queryKey: ['mission', missionId],
    queryFn: () => getMission(missionId!),
    enabled: Boolean(missionId),
    refetchInterval: ({ state }) => state.data?.checks.some((check) => ['QUEUED', 'RUNNING'].includes(check.status)) || state.data?.alerts.some((alert) => ['QUEUED', 'GENERATING'].includes(alert.audio_status)) ? 3000 : false,
  })

  useEffect(() => {
    if (!run || !options.data || initializedRun.current === run.id) return
    initializedRun.current = run.id
    setQuickPolicy(defaultPolicy(run, options.data))
  }, [options.data, run])

  const savePolicy = useMutation({
    mutationFn: async (policy: MonitoringPolicyInput) => {
      if (!missionId) return createMission(run!.id, policy)
      const updated = await updateMission(missionId, policy)
      return { mission_id: updated.id, status: updated.status }
    },
    onSuccess: async (result) => {
      setCreatedMissionId(result.mission_id)
      setDrawerOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['run', run?.id] })
      await queryClient.invalidateQueries({ queryKey: ['mission'] })
    },
  })
  const runCheck = useMutation({ mutationFn: () => checkMission(missionId!), onSuccess: (result) => onOpenRun?.(result.run_id) })
  const toggleStatus = useMutation({
    mutationFn: () => updateMission(missionId!, { status: mission.data?.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE' }),
    onSuccess: (updated) => queryClient.setQueryData(['mission', missionId], updated),
  })
  const retryDelivery = useMutation({
    mutationFn: () => retryAlertDelivery(missionId!, latestAlert!.id),
    onSuccess: (updated) => queryClient.setQueryData(['mission', missionId], mission.data ? {
      ...mission.data,
      alerts: mission.data.alerts.map((alert) => alert.id === updated.id ? updated : alert),
    } : mission.data),
  })
  const retryAudio = useMutation({
    mutationFn: () => retryAlertAudio(missionId!, latestAlert!.id),
    onSuccess: (updated) => queryClient.setQueryData(['mission', missionId], mission.data ? {
      ...mission.data,
      alerts: mission.data.alerts.map((alert) => alert.id === updated.id ? updated : alert),
    } : mission.data),
  })
  const latestAlert = mission.data?.alerts.at(-1)
  const running = mission.data?.checks.some((check) => ['QUEUED', 'RUNNING'].includes(check.status))
  const selectedOptions = options.data?.available_indicators.filter((item) => mission.data?.indicator_keys.includes(item.key)) || []
  const customized = Boolean(mission.data && options.data && hasCustomThresholds(
    options.data,
    mission.data.indicator_keys,
    mission.data.sensitivity,
    mission.data.metric_thresholds,
  ))
  const completedRun = run?.status === 'COMPLETED'
  const policyReady = completedRun && Boolean(quickPolicy && options.data)

  const toggleQuickIndicator = (key: string) => {
    if (!quickPolicy || !options.data) return
    const indicator = options.data.available_indicators.find((item) => item.key === key)
    if (!indicator) return
    const active = quickPolicy.indicator_keys.includes(key)
    const indicatorKeys = active
      ? quickPolicy.indicator_keys.filter((item) => item !== key)
      : [...quickPolicy.indicator_keys, key]
    const metricThresholds = { ...quickPolicy.metric_thresholds }
    const triggerDirections = { ...quickPolicy.trigger_directions }
    if (active) {
      delete metricThresholds[indicator.metric]
      delete triggerDirections[key]
    } else {
      metricThresholds[indicator.metric] = indicator.thresholds[quickPolicy.sensitivity]
      triggerDirections[key] = indicator.default_direction
    }
    setQuickPolicy({ ...quickPolicy, indicator_keys: indicatorKeys, metric_thresholds: metricThresholds, trigger_directions: triggerDirections })
  }

  const updateQuickCadence = (value: string) => {
    if (!quickPolicy) return
    if (value === 'custom') {
      setQuickPolicy({ ...quickPolicy, cadence_days: customCadence })
      return
    }
    setQuickPolicy({ ...quickPolicy, cadence_days: Number(value) })
  }

  const error = mission.error || options.error || savePolicy.error || runCheck.error || toggleStatus.error || retryDelivery.error || retryAudio.error

  return <article className="monitoring-card">
    <div className="monitoring-card__icon"><Radar size={20} /></div>
    {!mission.data ? <div className="monitoring-card__body"><span className="eyebrow">Monitoring policy</span><h3>Turn this investigation into a habitat watch</h3><p>{run?.status === 'COMPLETED' ? 'Choose what to watch and how often HabiWatch should refresh the evidence.' : 'Monitoring becomes available after a validated research run.'}</p></div> : <div className="monitoring-card__body"><div className="monitoring-heading"><div><span className="eyebrow">Monitoring {mission.data.status.toLowerCase()}</span><h3>{mission.data.name}</h3></div><span className={`monitoring-health ${latestAlert?.severity === 'attention' ? 'monitoring-health--attention' : ''}`}><i /> {latestAlert?.severity === 'attention' ? 'Review incident' : mission.data.status === 'ACTIVE' ? 'Healthy' : 'Paused'}</span></div><p>{mission.data.objective}</p><div className="monitoring-facts"><span><CalendarClock size={14} /> {cadenceLabel(mission.data.cadence_days)}</span><span><Activity size={14} /> {mission.data.indicator_keys.length} indicators</span><span><BellRing size={14} /> {mission.data.alerts.filter((alert) => alert.severity === 'attention').length} incidents</span><span><Music2 size={14} /> Audio {mission.data.audio_alert_enabled ? 'on' : 'off'}</span></div><div className="monitoring-tags">{selectedOptions.map((indicator) => <span key={indicator.key}>{indicator.label}</span>)}</div><div className="monitoring-next"><strong>{mission.data.sensitivity === 'IMPORTANT_ONLY' ? 'Important only' : mission.data.sensitivity.charAt(0) + mission.data.sensitivity.slice(1).toLowerCase()}{customized ? ' + custom' : ''}</strong><span>Next check {new Date(mission.data.next_check_at).toLocaleDateString()}</span></div>{latestAlert && <div className={`monitoring-incident ${latestAlert.severity === 'attention' ? 'monitoring-incident--attention' : ''}`}><strong>{latestAlert.title}</strong><span>{latestAlert.message}</span>{latestAlert.field_actions.length > 0 && <small>{latestAlert.field_actions.length} field-verification steps prepared</small>}</div>}</div>}

    {!mission.data && run?.status === 'COMPLETED' && quickPolicy && options.data && <div className="monitoring-quick" aria-label="Quick monitoring setup">
      <fieldset><legend>What to monitor</legend><div className="quick-indicators">{options.data.available_indicators.map((indicator) => { const active = quickPolicy.indicator_keys.includes(indicator.key); return <label key={indicator.key} className={active ? 'active' : ''}><input type="checkbox" checked={active} onChange={() => toggleQuickIndicator(indicator.key)} /><span>{active && <Check size={12} />}</span>{indicator.label}</label> })}</div></fieldset>
      <label className="quick-frequency"><span>Check frequency</span><select aria-label="Quick monitoring frequency" value={options.data.cadence_presets.some((item) => item.days === quickPolicy.cadence_days) ? quickPolicy.cadence_days : 'custom'} onChange={(event) => updateQuickCadence(event.target.value)}>{options.data.cadence_presets.map((preset) => <option key={preset.days} value={preset.days}>{preset.label}</option>)}<option value="custom">Custom</option></select></label>
      {!options.data.cadence_presets.some((item) => item.days === quickPolicy.cadence_days) && <label className="quick-custom-frequency">Every <input aria-label="Quick custom monitoring frequency in days" type="number" min={1} max={365} value={customCadence} onChange={(event) => { const days = Number(event.target.value); setCustomCadence(days); setQuickPolicy({ ...quickPolicy, cadence_days: days }) }} /> days</label>}
      <small>Any selected indicator crossing its validated threshold creates an incident.</small>
    </div>}

    {!mission.data && !completedRun && <div className="monitoring-locked" role="status"><LockKeyhole size={15} /><span><strong>Advanced settings unlock after validation</strong><small>Complete a research run first so HabiWatch can offer only indicators supported by its evidence.</small></span></div>}
    <div className="monitoring-actions">
      {!mission.data && completedRun && <><button className="secondary-button" disabled={!policyReady} onClick={() => setDrawerOpen(true)}>{policyReady ? <Settings2 size={15} /> : <LoaderCircle className="spin" size={15} />} {policyReady ? 'Advanced settings' : 'Loading settings…'}</button><button className="mission-button" disabled={!quickPolicy || !options.data || quickPolicy.indicator_keys.length === 0 || quickPolicy.cadence_days < 1 || quickPolicy.cadence_days > 365 || savePolicy.isPending} onClick={() => quickPolicy && savePolicy.mutate(quickPolicy)}><Radar size={15} /> {savePolicy.isPending ? 'Activating…' : 'Activate monitoring'}</button></>}
      {mission.data && <><button className="secondary-button" onClick={() => setDrawerOpen(true)}><Settings2 size={15} /> Edit policy</button><button className="secondary-button" disabled={toggleStatus.isPending} onClick={() => toggleStatus.mutate()}>{mission.data.status === 'ACTIVE' ? <Pause size={15} /> : <Play size={15} />} {mission.data.status === 'ACTIVE' ? 'Pause' : 'Resume'}</button><button className="mission-button" disabled={runCheck.isPending || running || mission.data.status !== 'ACTIVE'} onClick={() => runCheck.mutate()}><RefreshCw size={15} className={runCheck.isPending ? 'spin' : ''} /> {runCheck.isPending ? 'Starting…' : 'Run now'}</button></>}
    </div>
    {latestAlert?.severity === 'attention' && <section className="incident-command" aria-label="Incident command">
      <header><div><span className="eyebrow"><ClipboardCheck size={13} /> Incident command</span><strong>{latestAlert.title}</strong></div><span className={`delivery-state delivery-state--${String(latestAlert.delivery?.status || 'prepared')}`}>{String(latestAlert.delivery?.status || 'prepared')}</span></header>
      <div className="incident-loop" aria-label="Detect verify decide dispatch monitor workflow">{['Detect', 'Verify', 'Decide', 'Dispatch', 'Monitor'].map((step, index) => { const waitingToDispatch = index === 3 && latestAlert.delivery?.status !== 'delivered'; return <span key={step} className={latestAlert.delivery?.status === 'failed' && waitingToDispatch ? 'warning' : waitingToDispatch ? 'active' : 'complete'}><i />{step}</span> })}</div>
      <p>{latestAlert.message}</p>
      {latestAlert.audio_status !== 'NOT_REQUESTED' && <div className={`incident-audio incident-audio--${latestAlert.audio_status.toLowerCase()}`}><div><Music2 size={16} /><span><strong>Lyria Habitat Pulse</strong><small>AI-generated operational audio—not scientific evidence.</small></span></div>{latestAlert.audio_status === 'COMPLETED' && latestAlert.audio_artifact_id && <><audio controls preload="metadata" src={artifactUrl(`/api/v1/runs/${latestAlert.run_id}/artifacts/${latestAlert.audio_artifact_id}`)} /><a className="secondary-button" download href={artifactUrl(`/api/v1/runs/${latestAlert.run_id}/artifacts/${latestAlert.audio_artifact_id}`)}><Download size={14} /> MP3</a></>}{['QUEUED', 'GENERATING'].includes(latestAlert.audio_status) && <span className="audio-progress"><LoaderCircle className="spin" size={14} /> {latestAlert.audio_status === 'QUEUED' ? 'Queued' : 'Generating'}</span>}{latestAlert.audio_status === 'FAILED' && <button className="secondary-button" disabled={retryAudio.isPending} onClick={() => retryAudio.mutate()}><RefreshCw className={retryAudio.isPending ? 'spin' : ''} size={14} /> Retry audio</button>}</div>}
      {(latestAlert.field_tasks || []).length > 0 && <div className="incident-tasks">{(latestAlert.field_tasks || []).map((task) => <article key={task.id}><span>{task.priority}</span><strong>{task.title}</strong><small>{task.instructions}</small>{task.coordinates && <em>{task.coordinates[1].toFixed(4)}, {task.coordinates[0].toFixed(4)}</em>}</article>)}</div>}
      <footer>{latestAlert.action_packet_artifact_id && <a className="secondary-button" href={artifactUrl(`/api/v1/runs/${latestAlert.run_id}/artifacts/${latestAlert.action_packet_artifact_id}`)}><Download size={14} /> Action packet</a>}{latestAlert.delivery?.status === 'failed' && <button className="secondary-button" disabled={retryDelivery.isPending} onClick={() => retryDelivery.mutate()}><RefreshCw size={14} className={retryDelivery.isPending ? 'spin' : ''} /> Retry delivery</button>}</footer>
    </section>}
    {error && <p className="card-error">{error.message}</p>}
    {drawerOpen && run && options.data && <MonitoringPolicyDrawer run={run} options={options.data} mission={mission.data} initialPolicy={quickPolicy} saving={savePolicy.isPending} error={savePolicy.error} onClose={() => setDrawerOpen(false)} onSave={(policy) => savePolicy.mutate(policy)} />}
  </article>
}
