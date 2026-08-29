import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CalendarDays, Database, FileCheck2, FlaskConical, Radar, Search } from 'lucide-react'
import { listRuns } from '../../api/runs'
import type { RunStatus } from '../../types/run'

const terminalStatuses: RunStatus[] = ['COMPLETED', 'FAILED', 'CANCELLED']

function formatStatus(status: RunStatus) {
  return status.toLowerCase().replaceAll('_', ' ')
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(new Date(value))
}

export function RunsView({ onOpenRun, onStartResearch }: { onOpenRun: (runId: string) => void; onStartResearch: () => void }) {
  const [search, setSearch] = useState('')
  const query = useQuery({
    queryKey: ['runs'],
    queryFn: listRuns,
    refetchInterval: ({ state }) => state.data?.some((run) => !terminalStatuses.includes(run.status)) ? 3000 : false,
  })
  const runs = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (query.data || []).filter((run) => !needle || run.user_query.toLowerCase().includes(needle) || run.status.toLowerCase().includes(needle))
  }, [query.data, search])

  return <section className="library-page" aria-labelledby="runs-title">
    <div className="library-hero">
      <div><span className="eyebrow"><FlaskConical size={14} /> Research archive</span><h1 id="runs-title">Research runs</h1><p>Reopen an investigation, review its progress, or return to completed evidence.</p></div>
      <button className="primary-button" onClick={onStartResearch}>Start new research <ArrowRight size={17} /></button>
    </div>
    <div className="library-toolbar">
      <label className="library-search"><Search size={18} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search questions or status" /></label>
      <span>{runs.length} {runs.length === 1 ? 'run' : 'runs'}</span>
    </div>

    {query.isLoading && <div className="library-message">Loading research runs…</div>}
    {query.isError && <div className="library-message library-message--error">Unable to load runs: {query.error.message}</div>}
    {!query.isLoading && !query.isError && runs.length === 0 && <div className="library-empty"><FlaskConical size={28} /><h2>No research runs found</h2><p>{search ? 'Try a different search.' : 'Start a research question and it will appear here.'}</p></div>}

    <div className="run-list">
      {runs.map((run) => <article className="run-card" key={run.id}>
        <div className="run-card__top"><span className={`status-badge status-badge--${run.status.toLowerCase()}`}>{formatStatus(run.status)}</span><span className="run-date"><CalendarDays size={15} /> {formatDate(run.updated_at)}</span></div>
        <h2>{run.user_query}</h2>
        {run.final_summary && <p className="run-summary">{run.final_summary}</p>}
        {run.error && <p className="run-summary run-summary--error">{run.error.message}</p>}
        <div className="run-progress" aria-label={`${run.progress}% complete`}><div style={{ width: `${run.progress}%` }} /></div>
        <div className="run-card__footer">
          <div className="run-facts"><span><Database size={16} /> {run.selected_dataset_count} datasets</span><span><FileCheck2 size={16} /> {run.artifact_count} artifacts</span>{run.monitoring_mission_id && <span className="mission-fact"><Radar size={16} /> Habitat watch</span>}<span>{run.progress}% complete</span></div>
          <button onClick={() => onOpenRun(run.id)}>Open workspace <ArrowRight size={16} /></button>
        </div>
      </article>)}
    </div>
  </section>
}
