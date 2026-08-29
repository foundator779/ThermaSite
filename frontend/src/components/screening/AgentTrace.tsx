import { Check, CircleDashed, TriangleAlert } from 'lucide-react'
import type { ScreeningEvent, ScreeningStatus } from '../../types/screening'

const stageLabels: Record<string, string> = {
  CREATED: 'Queued', PLANNING: 'Planning', ACQUIRING_HEAT: 'FortyGuard',
  RESEARCHING_SITES: 'Site intelligence', SCORING: 'Scoring', AUDITING: 'Audit',
  REPORTING: 'Memo', COMPLETED: 'Complete', FAILED: 'Stopped', CANCELLED: 'Cancelled',
}

export function AgentTrace({ events, status, progress }: {
  events: ScreeningEvent[]
  status: ScreeningStatus
  progress: number
}) {
  return <aside className="agent-trace">
    <div className="trace-head">
      <div><span className="eyebrow">Live execution</span><h2>Agent activity</h2></div>
      <span className={`status-dot status-dot--${status.toLowerCase()}`}>{stageLabels[status]}</span>
    </div>
    <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
    <div className="trace-list">
      {events.length === 0 && <div className="trace-empty"><CircleDashed size={17} /> Waiting for a screening.</div>}
      {events.slice(-12).map((event) => <article className={`trace-event trace-event--${event.status}`} key={event.id}>
        <span className="trace-icon">{event.status === 'error' || event.status === 'warning' ? <TriangleAlert size={13} /> : <Check size={13} />}</span>
        <div><strong>{event.message}</strong><span>{event.agent} · {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span></div>
      </article>)}
    </div>
    <p className="trace-note">Action trace only. ThermaSite exposes tool outcomes and decision rationale, never private model reasoning.</p>
  </aside>
}
