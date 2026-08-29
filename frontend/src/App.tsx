import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight, Building2, Check, ChevronRight, Cpu, Database, Droplets, Gauge, Menu, Plus,
  RotateCcw, LogOut, Search, ShieldCheck, SlidersHorizontal, Sparkles, ThermometerSun,
  UserRound, Zap,
} from 'lucide-react'
import { enterDemo, getMe, login, logout, register, type AuthUser } from './api/auth'
import { getSessionToken } from './api/client'
import {
  createScreening, DEFAULT_COOLING, DEFAULT_FACILITY, DEFAULT_WEIGHTS, getSiteCatalog,
  listScreenings, rescoreScreening,
} from './api/screenings'
import { getReadiness } from './api/system'
import { AgentTrace } from './components/screening/AgentTrace'
import { EvidenceDrawer } from './components/screening/EvidenceDrawer'
import { FacilityImpact } from './components/screening/FacilityImpact'
import { ScreeningMap } from './components/screening/ScreeningMap'
import { useScreening } from './hooks/useScreening'
import type {
  CoolingScenario, FacilityRequirements, FactorWeights, ScreeningRecord, SiteRecommendation,
} from './types/screening'

const DEFAULT_BRIEF = 'Find the five strongest U.S. locations for this data-center campus. Balance FortyGuard heat, facility power, water exposure, permitting readiness, and infrastructure.'
const factorLabels: Record<keyof FactorWeights, string> = {
  thermal: 'Thermal', power: 'Power', water: 'Water', permitting: 'Permitting', logistics: 'Infrastructure',
}

function money(value?: number) {
  if (value === undefined) return 'Pending'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value)
}

function siteFor(record: ScreeningRecord | undefined, siteId?: string) {
  return record?.candidates.find((site) => site.id === siteId)
}

function recommendationFor(record: ScreeningRecord | undefined, siteId?: string) {
  return record?.recommendations.find((item) => item.site_id === siteId)
}

function ScorePill({ recommendation }: { recommendation?: SiteRecommendation }) {
  if (!recommendation?.rankable) return <span className="score-pill score-pill--muted">Unranked</span>
  return <span className="score-pill">{recommendation.score?.toFixed(1)}</span>
}

export default function App() {
  const queryClient = useQueryClient()
  const [screeningId, setScreeningId] = useState<string>()
  const [view, setView] = useState<'screen' | 'history'>('screen')
  const [menuOpen, setMenuOpen] = useState(false)
  const [brief, setBrief] = useState(DEFAULT_BRIEF)
  const [facility, setFacility] = useState<FacilityRequirements>(DEFAULT_FACILITY)
  const [selectedId, setSelectedId] = useState<string>()
  const [weights, setWeights] = useState<FactorWeights>(DEFAULT_WEIGHTS)
  const [cooling, setCooling] = useState<CoolingScenario>(DEFAULT_COOLING)
  const [evidenceOpen, setEvidenceOpen] = useState(false)

  const hasSession = Boolean(getSessionToken())
  const auth = useQuery({ queryKey: ['auth', 'me'], queryFn: getMe, enabled: hasSession, retry: false })
  const user = hasSession ? auth.data : undefined
  const savedScreeningId = user ? localStorage.getItem(`thermasite:last-screening:${user.id}`) || undefined : undefined
  const activeScreeningId = screeningId || savedScreeningId
  const catalog = useQuery({ queryKey: ['site-catalog'], queryFn: getSiteCatalog, enabled: Boolean(user) })
  const readiness = useQuery({ queryKey: ['readiness'], queryFn: getReadiness, refetchInterval: 20_000 })
  const history = useQuery({ queryKey: ['screenings'], queryFn: listScreenings, enabled: view === 'history' && Boolean(user) })
  const screening = useScreening(user ? activeScreeningId : undefined)
  const record = screening.data
  const create = useMutation({
    mutationFn: createScreening,
    onSuccess: (result) => {
      setScreeningId(result.screening_id)
      if (user) localStorage.setItem(`thermasite:last-screening:${user.id}`, result.screening_id)
      setView('screen')
      queryClient.invalidateQueries({ queryKey: ['screenings'] })
    },
  })
  const rescore = useMutation({
    mutationFn: () => rescoreScreening(activeScreeningId!, weights),
    onSuccess: (next) => queryClient.setQueryData(['screening', activeScreeningId], next),
  })
  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      setScreeningId(undefined)
      queryClient.removeQueries({ queryKey: ['auth'] })
    },
  })

  const ranked = useMemo(() => [...(record?.recommendations || [])].sort((a, b) => (a.rank || 99) - (b.rank || 99)), [record])
  const orderedCandidates = useMemo(() => [...(record?.candidates || [])].sort((a, b) => (recommendationFor(record, a.id)?.rank || 99) - (recommendationFor(record, b.id)?.rank || 99)), [record])
  const leader = ranked.find((item) => item.rank === 1 && item.eligible)
  const effectiveSelectedId = record?.candidates.some((site) => site.id === selectedId) ? selectedId : leader?.site_id || record?.candidates[0]?.id
  const selected = siteFor(record, effectiveSelectedId)
  const selectedRecommendation = recommendationFor(record, effectiveSelectedId)
  const latestEstimate = [...(record?.resource_estimates || [])].reverse().find((item) => item.site_id === effectiveSelectedId)
  const leaderSite = siteFor(record, leader?.site_id)
  const running = record && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(record.status)
  const plannedItLoad = Math.round(facility.facility_size_acres * facility.it_density_mw_per_acre * 10) / 10
  const canLaunch = brief.trim().length >= 12 && plannedItLoad > 0 && plannedItLoad <= 1000
  const launch = () => create.mutate({
    brief,
    facility,
    weights,
    cooling: { ...cooling, it_load_mw: plannedItLoad },
  })
  const newScreening = () => {
    setScreeningId(undefined)
    if (user) localStorage.removeItem(`thermasite:last-screening:${user.id}`)
    setSelectedId(undefined)
    setView('screen')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  if (hasSession && auth.isLoading) return <div className="auth-loading"><span className="wordmark"><span>Therma</span><strong>Site</strong></span><p>Restoring your workspace…</p></div>
  if (!user) return <AuthLanding onAuthenticated={(account) => queryClient.setQueryData(['auth', 'me'], account)} />

  return <div className="app-shell">
    <header className="site-header">
      <button className="wordmark" onClick={newScreening} aria-label="ThermaSite home">
        <span>Therma</span><strong>Site</strong><i>Track 3</i>
      </button>
      <nav className={menuOpen ? 'open' : ''} aria-label="Primary navigation">
        <button className={view === 'screen' ? 'active' : ''} onClick={() => { setView('screen'); setMenuOpen(false) }}>Screener</button>
        <button className={view === 'history' ? 'active' : ''} onClick={() => { setView('history'); setMenuOpen(false) }}>Decisions</button>
        <a href="#method">Method</a>
      </nav>
      <div className="header-status">
        <span className={readiness.data?.checks?.fortyguard?.configured ? 'online' : ''} />
        FortyGuard {readiness.data?.checks?.fortyguard?.configured ? 'ready' : 'key required'}
      </div>
      <div className="account-chip"><UserRound size={13} /><span>{user.is_demo ? 'Judge demo' : user.name}</span><button onClick={() => signOut.mutate()} aria-label="Sign out"><LogOut size={13} /></button></div>
      <button className="menu-toggle" onClick={() => setMenuOpen((value) => !value)} aria-label="Toggle navigation"><Menu /></button>
    </header>

    {view === 'history' ? <HistoryView records={history.data || []} loading={history.isLoading} onOpen={(id) => { setScreeningId(id); localStorage.setItem(`thermasite:last-screening:${user.id}`, id); setView('screen') }} onNew={newScreening} /> : <main>
      {!record && <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow"><Sparkles size={13} /> Facility-first site intelligence</span>
          <h1>Describe the facility. Get the <em>five places</em> built for it.</h1>
          <p>Start with the campus you intend to build. ThermaSite generates same-scale U.S. footprints, asks FortyGuard how heat changes the operating load, and returns five cited locations.</p>
          <div className="hero-proof"><span><Search /> {catalog.data?.sites.length || 8} sourced U.S. markets</span><span><Building2 /> Same-scale AOIs</span><span><Zap /> Heat-adjusted power</span></div>
        </div>
        <div className="launcher-card facility-launcher">
          <div className="launcher-title"><span className="eyebrow">01 · Define the build</span><strong>Your facility profile</strong></div>
          <label className="size-field"><span>Campus footprint<strong>{facility.facility_size_acres} acres</strong></span><input aria-label="Campus footprint, acres" type="range" min="5" max="200" step="5" value={facility.facility_size_acres} onChange={(event) => setFacility((current) => ({ ...current, facility_size_acres: Number(event.target.value) }))} /></label>
          <div className="facility-input-grid">
            <label><span>Campus size, acres</span><input aria-label="Campus size, acres" type="number" min="1" max="640" value={facility.facility_size_acres} onChange={(event) => setFacility((current) => ({ ...current, facility_size_acres: Number(event.target.value) }))} /></label>
            <label><span>IT design density</span><select aria-label="IT design density" value={facility.it_density_mw_per_acre} onChange={(event) => setFacility((current) => ({ ...current, it_density_mw_per_acre: Number(event.target.value) }))}><option value="0.75">Conservative · 0.75 MW/acre</option><option value="1.25">Balanced · 1.25 MW/acre</option><option value="2">Dense · 2.00 MW/acre</option></select></label>
            <label><span>Cooling architecture</span><select aria-label="Cooling architecture" value={facility.cooling_system} onChange={(event) => setFacility((current) => ({ ...current, cooling_system: event.target.value as FacilityRequirements['cooling_system'] }))}><option value="dry">Dry / air</option><option value="evaporative">Evaporative</option><option value="hybrid">Hybrid</option><option value="liquid">Liquid</option></select></label>
            <label><span>Expected utilization</span><input aria-label="Expected utilization, percent" type="number" min="1" max="100" value={Math.round(cooling.utilization * 100)} onChange={(event) => setCooling((current) => ({ ...current, utilization: Number(event.target.value) / 100 }))} /></label>
          </div>
          <div className="capacity-preview"><Cpu /><span><small>Derived planning profile</small><strong>{plannedItLoad.toFixed(1)} MW IT</strong></span><i>×</i><span><small>Baseline PUE</small><strong>{cooling.baseline_pue.toFixed(2)}</strong></span><i>→</i><span><small>Five finalists</small><strong>Nationwide</strong></span></div>
          <details className="brief-details"><summary>Investment priorities</summary><textarea id="screening-brief" aria-label="Investment priorities" value={brief} onChange={(event) => setBrief(event.target.value)} rows={3} /></details>
          <div className="launcher-meta"><span>July 2026</span><span>35°C threshold</span><span>100 m analysis</span></div>
          <button className="primary-action" disabled={!canLaunch || create.isPending} onClick={launch}>
            {create.isPending ? 'Starting site agents…' : 'Find my top five locations'} <ArrowRight size={17} />
          </button>
          {create.error && <p className="inline-error">{create.error.message}</p>}
        </div>
      </section>}

      {record && <>
        <section className="screening-head">
          <div><span className="eyebrow">Top-five facility search · {record.id.slice(0, 8)}</span><h1>{running ? record.current_step : leaderSite ? `${leaderSite.metro} fits best.` : 'Review the evidence.'}</h1><p>{record.summary || record.request.brief}</p></div>
          <div className="screening-actions"><button className="quiet-button" onClick={newScreening}><Plus size={15} /> New screen</button><button className="secondary-action" onClick={() => setEvidenceOpen(true)}><Database size={15} /> Evidence & memo</button></div>
        </section>

        <section className="facility-summary-strip">
          <div><Building2 /><span><small>Campus footprint</small><strong>{record.request.facility.facility_size_acres.toFixed(0)} acres</strong></span></div>
          <div><Cpu /><span><small>Planned IT capacity</small><strong>{record.request.cooling.it_load_mw.toFixed(1)} MW</strong></span></div>
          <div><Gauge /><span><small>Operating profile</small><strong>{Math.round(record.request.cooling.utilization * 100)}% · PUE {record.request.cooling.baseline_pue.toFixed(2)}</strong></span></div>
          <div><Droplets /><span><small>Cooling architecture</small><strong>{record.request.facility.cooling_system}</strong></span></div>
          <div><Search /><span><small>Agent output</small><strong>{record.candidates.length || 5} finalists</strong></span></div>
        </section>

        {record.error && <div className="error-banner"><strong>{record.error.code}</strong><span>{record.error.message}</span><button onClick={newScreening}>Try a new screening</button></div>}

        <section className="workspace">
          <div className="map-panel">
            <ScreeningMap sites={orderedCandidates} selectedId={effectiveSelectedId} onSelect={setSelectedId} footprint={latestEstimate?.polygon} footprintLabel={`${record.request.facility.facility_size_acres.toFixed(0)}-acre concept · industrial edge`} />
            <div className="map-legend"><span>Ambient heat</span><i className="cool" /><i /><i /><i className="hot" /><small>Lower</small><small>Higher</small></div>
            <div className="map-caption">Satellite context · industrial-edge search zone · FortyGuard · 100 m · July 2026 · illustrative footprint, not parcel availability</div>
          </div>
          <div className="rank-panel">
            <div className="panel-heading"><span className="eyebrow">Agent shortlist</span><strong>Top {record.candidates.length || 5}</strong></div>
            <div className="rank-list">{orderedCandidates.map((site) => {
              const recommendation = recommendationFor(record, site.id)
              const projection = record.resource_estimates.find((item) => item.site_id === site.id)
              return <button key={site.id} className={effectiveSelectedId === site.id ? 'rank-card active' : 'rank-card'} onClick={() => setSelectedId(site.id)}>
                <span className="rank-position">{recommendation?.rank ? `0${recommendation.rank}` : '—'}</span>
                <span><strong>{site.metro}</strong><small>{site.state} · {projection ? `${projection.average_facility_power_mw.toFixed(1)} MW average` : 'Awaiting FortyGuard'}</small></span>
                <ScorePill recommendation={recommendation} />
              </button>
            })}</div>
            {selected && <div className="site-snapshot">
              <div><span>Mean</span><strong>{selected.thermal ? `${selected.thermal.mean_temperature_c.toFixed(1)}°C` : '—'}</strong></div>
              <div><span>Average facility</span><strong>{latestEstimate ? `${latestEstimate.average_facility_power_mw.toFixed(1)} MW` : '—'}</strong></div>
              <div><span>Peak service</span><strong>{latestEstimate ? `${latestEstimate.peak_facility_power_mw.toFixed(1)} MW` : '—'}</strong></div>
              <div><span>Readiness</span><strong>{selectedRecommendation ? `${Math.round(selectedRecommendation.decision_readiness * 100)}%` : '—'}</strong></div>
            </div>}
          </div>
          <AgentTrace events={screening.events} status={record.status} progress={record.progress} />
        </section>

        <FacilityImpact site={selected} estimate={latestEstimate} recommendation={selectedRecommendation} />

        <section className="decision-section">
          <header><div><span className="eyebrow">Deterministic decision model</span><h2>One score. Every tradeoff visible.</h2></div>{record.status === 'COMPLETED' && <span className="audit-badge"><Check size={14} /> {record.audit?.passed ? 'Evidence audited' : 'Review required'}</span>}</header>
          <div className="factor-grid">
            {ranked.map((recommendation) => {
              const site = siteFor(record, recommendation.site_id)
              return <article key={recommendation.site_id} className={recommendation.rank === 1 ? 'result-card result-card--leader' : 'result-card'}>
                <div className="result-top"><span>{recommendation.rank ? `Rank ${recommendation.rank}` : 'Not ranked'}</span><ScorePill recommendation={recommendation} /></div>
                <h3>{site?.metro || recommendation.site_id}</h3>
                <p>{recommendation.eligible ? 'Eligible under active hard constraints.' : recommendation.constraint_failures.join(' ')}</p>
                <div className="factor-bars">{recommendation.factor_scores.map((factor) => <div key={factor.factor} title={factor.detail}>
                  <span>{factorLabels[factor.factor as keyof FactorWeights]}</span><i><b style={{ width: `${factor.score}%` }} /></i><strong>{factor.score.toFixed(0)}</strong>
                </div>)}</div>
                <dl><div><dt>Cooling burden</dt><dd>{recommendation.cooling_burden_index?.toFixed(1) || '—'}</dd></div><div><dt>Window cooling scenario</dt><dd>{money(recommendation.selected_window_cooling_cost_usd)}</dd></div>{recommendation.illustrative_annual_cooling_cost_usd !== undefined && <div><dt>Illustrative annualized</dt><dd>{money(recommendation.illustrative_annual_cooling_cost_usd)}</dd></div>}</dl>
              </article>
            })}
            {!ranked.length && <div className="results-pending"><Gauge size={22} /><strong>Scores arrive after the heat and evidence agents complete.</strong><span>Missing FortyGuard data leaves a site visible but unranked.</span></div>}
          </div>
        </section>

        <section className="tuning-section" id="method">
          <div className="tuning-copy"><span className="eyebrow"><SlidersHorizontal size={13} /> Scenario lab</span><h2>Change the investment lens.</h2><p>Weights normalize to 100%. Rescoring uses stored FortyGuard and site evidence and never repeats external research.</p><div className="scenario-stat"><ThermometerSun /><span><small>Fixed facility profile</small><strong>{record.request.facility.facility_size_acres.toFixed(0)} acres · {record.request.cooling.it_load_mw.toFixed(1)} MW</strong></span></div></div>
          <div className="weight-editor">{(Object.keys(weights) as Array<keyof FactorWeights>).map((key) => <label key={key}><span>{factorLabels[key]}<strong>{weights[key]}%</strong></span><input type="range" min="0" max="70" value={weights[key]} onChange={(event) => setWeights((current) => ({ ...current, [key]: Number(event.target.value) }))} /></label>)}
            <div className="editor-actions"><button onClick={() => setWeights(DEFAULT_WEIGHTS)}><RotateCcw size={14} /> Reset</button><button className="primary-action" disabled={!activeScreeningId || !record.recommendations.length || rescore.isPending} onClick={() => rescore.mutate()}>{rescore.isPending ? 'Recalculating…' : 'Apply weights'} <ArrowRight size={15} /></button></div>
          </div>
        </section>

        <section className="verify-section"><div><span className="eyebrow">What to verify next</span><h2>Diligence queue</h2></div><ol>{record.due_diligence.map((item, index) => <li key={item}><span>{String(index + 1).padStart(2, '0')}</span>{item}</li>)}</ol></section>
      </>}

      <section className="method-strip" id="method-overview"><span>01 · FortyGuard heat</span><ChevronRight /><span>02 · Grounded site facts</span><ChevronRight /><span>03 · Deterministic scoring</span><ChevronRight /><span>04 · Independent audit</span></section>
    </main>}
    <EvidenceDrawer record={record} open={evidenceOpen} onClose={() => setEvidenceOpen(false)} />
    <footer className="site-footer"><span>ThermaSite</span><p>Screening intelligence for data-center decisions. Not engineering, legal, water-rights, or utility-capacity advice.</p><small>FortyGuard Hackathon ’26 · Track 3</small></footer>
  </div>
}

function AuthLanding({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const authenticate = useMutation({
    mutationFn: () => mode === 'login' ? login({ email, password }) : register({ name, email, password }),
    onSuccess: onAuthenticated,
  })
  const demo = useMutation({ mutationFn: enterDemo, onSuccess: onAuthenticated })
  const valid = email.includes('@') && password.length >= 8 && (mode === 'login' || name.trim().length >= 2)
  return <main className="auth-page">
    <section className="auth-story"><button className="wordmark" aria-label="ThermaSite home"><span>Therma</span><strong>Site</strong><i>Track 3</i></button><div><span className="eyebrow"><Sparkles size={13} /> Agentic infrastructure intelligence</span><h1>Decisions this large should remember <em>everything.</em></h1><p>Persistent, cited screening intelligence for the next generation of data-center infrastructure.</p></div><footer>FortyGuard Hackathon ’26 · Industrial & Enterprise</footer></section>
    <section className="auth-panel"><div className="auth-card"><span className="eyebrow">Private workspace</span><h2>{mode === 'login' ? 'Welcome back.' : 'Create your workspace.'}</h2><p>{mode === 'login' ? 'Your screenings, evidence, and saved scenarios are waiting.' : 'Keep every shortlist and decision memo attached to your account.'}</p>
      <div className="auth-tabs"><button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>Log in</button><button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Register</button></div>
      <form onSubmit={(event) => { event.preventDefault(); if (valid) authenticate.mutate() }}>
        {mode === 'register' && <label>Name<input autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" /></label>}
        <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" /></label>
        <label>Password<input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="8 characters minimum" /></label>
        {authenticate.error && <p className="inline-error">{authenticate.error.message}</p>}
        <button className="primary-action auth-submit" disabled={!valid || authenticate.isPending}>{authenticate.isPending ? 'Opening workspace…' : mode === 'login' ? 'Log in' : 'Create account'} <ArrowRight size={15} /></button>
      </form>
      <div className="auth-divider"><span>or</span></div>
      <button className="demo-account" onClick={() => demo.mutate()} disabled={demo.isPending}><ShieldCheck size={17} /><span><strong>{demo.isPending ? 'Opening demo…' : 'Enter judge demo'}</strong><small>No credentials required · saved shared workspace</small></span><ArrowRight size={15} /></button>
      {demo.error && <p className="inline-error">{demo.error.message}</p>}
      <small className="auth-note">ThermaSite stores password hashes and revocable session tokens. The public demo contains hackathon-only sample work.</small>
    </div></section>
  </main>
}

function HistoryView({ records, loading, onOpen, onNew }: { records: ScreeningRecord[]; loading: boolean; onOpen: (id: string) => void; onNew: () => void }) {
  return <main className="history-page"><header><div><span className="eyebrow">Decision archive</span><h1>Previous screenings.</h1><p>Reopen the evidence, ranks, and memo behind every shortlist.</p></div><button className="primary-action" onClick={onNew}><Plus size={15} /> New screening</button></header>
    {loading && <p className="history-empty">Loading decision records…</p>}
    {!loading && !records.length && <p className="history-empty">No screening records yet.</p>}
    <div className="history-list">{records.map((record) => <button key={record.id} onClick={() => onOpen(record.id)}><span className={`history-status history-status--${record.status.toLowerCase()}`}>{record.status}</span><span><strong>{record.candidates.map((site) => site.metro).join(' · ') || 'Candidate screening'}</strong><small>{new Date(record.created_at).toLocaleString()} · {record.current_step}</small></span><span>{record.progress}% <ChevronRight size={16} /></span></button>)}</div>
  </main>
}
