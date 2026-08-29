import { AlertTriangle, Check, Circle, LoaderCircle, RotateCcw, X } from 'lucide-react'
import type { RunEvent, RunRecord } from '../../types/run'

function iconFor(event: RunEvent, isLast: boolean, terminal: boolean) {
  if (event.status === 'error' || event.type.endsWith('failed')) return <X size={13} />
  if (event.type.startsWith('repair.')) return <RotateCcw size={13} />
  if (event.status === 'warning') return <AlertTriangle size={13} />
  if (isLast && !terminal) return <LoaderCircle size={13} className="spin" />
  return <Check size={13} />
}

export function AgentTimeline({ run, events }: { run?: RunRecord; events: RunEvent[] }) {
  const visible = events.filter((event) => !event.type.includes('candidate')).slice(-10)
  const terminal = run ? ['COMPLETED', 'FAILED', 'CANCELLED'].includes(run.status) : false
  return <aside className="timeline-panel" aria-label="Live autonomous agent timeline">
    <header>
      <div><span className="eyebrow">Live workflow</span><h2>Research agents</h2></div>
      <span className={`run-state state-${(run?.status || 'idle').toLowerCase()}`}><i />{run?.status.replaceAll('_', ' ') || 'Ready'}</span>
    </header>
    <div className="progress-track"><div style={{ width: `${run?.progress || 0}%` }} /></div>
    <div className="timeline-list">
      {visible.length === 0 && <div className="timeline-empty"><Circle size={14} /> Waiting for a research run</div>}
      {visible.map((event, index) => <div className={`timeline-item ${event.status === 'error' || event.type.endsWith('failed') ? 'timeline-item--error' : ''}`} key={event.id}>
        <div className="timeline-icon">{iconFor(event, index === visible.length - 1, terminal)}</div>
        <div><strong>{event.message}</strong><span>{event.agent} · {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span></div>
      </div>)}
    </div>
    {run?.harmonization && <div className="overlap-note"><Check size={14} /><span><strong>Validated overlap</strong>{run.harmonization.overlap_start.slice(0, 4)}–{run.harmonization.overlap_end.slice(0, 4)} · {run.harmonization.paired_sample_count} paired months</span></div>}
  </aside>
}
