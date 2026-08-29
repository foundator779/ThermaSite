import { BadgeDollarSign, Droplets, Gauge, Info, ShieldCheck, Zap } from 'lucide-react'
import type { ScreeningRecord } from '../../types/screening'

function compact(value: number, unit: string) {
  return `${new Intl.NumberFormat('en-US', {
    notation: value >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: value >= 1000 ? 0 : 1,
  }).format(value)} ${unit}`
}

function money(value?: number) {
  if (value === undefined) return 'Evidence unavailable'
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', notation: value >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  }).format(value)
}

export function DecisionCase({ record }: { record: ScreeningRecord }) {
  const analysis = record.decision_analysis
  if (!analysis) return null
  const sites = new Map(record.candidates.map((site) => [site.id, site]))
  const leader = sites.get(analysis.leader_site_id)
  const hottest = sites.get(analysis.hottest_site_id)
  const costliest = analysis.costliest_site_id ? sites.get(analysis.costliest_site_id) : undefined

  return <section className="decision-case" id="investment-case">
    <header className="decision-case__heading">
      <div><span className="eyebrow"><ShieldCheck size={13} /> Investment case stress test</span><h2>Will the winner survive a different boardroom?</h2><p>ThermaSite replays the same audited evidence through five decision strategies. It also translates the selected July window into a comparable operating consequence. No model changes the scores and no additional provider call is made.</p></div>
      <span className={`robustness-badge robustness-badge--${analysis.robustness_label}`}>{analysis.robustness_label} decision</span>
    </header>

    <div className="decision-case__grid">
      <article className="consensus-card">
        <span>Recommendation durability</span>
        <strong>{analysis.robustness_wins}<i>/{analysis.robustness_total}</i></strong>
        <h3>{leader?.metro || analysis.leader_site_id} stays first.</h3>
        <p>Wins across current, thermal-first, power-first, water-first, and delivery-speed strategies.</p>
      </article>
      <div className="business-metrics">
        <article><BadgeDollarSign /><span>July cost advantage</span><strong>{money(analysis.window_cost_advantage_usd)}</strong><small>Versus highest-cost finalist {costliest?.metro ? `(${costliest.metro})` : ''}</small></article>
        <article><Zap /><span>Energy avoided</span><strong>{compact(analysis.window_energy_avoided_mwh, 'MWh')}</strong><small>Versus hottest finalist {hottest?.metro ? `(${hottest.metro})` : ''}</small></article>
        <article><Droplets /><span>Direct water avoided</span><strong>{compact(analysis.window_water_avoided_gallons_low, 'gal')}–{compact(analysis.window_water_avoided_gallons_high, 'gal')}</strong><small>Same facility and cooling architecture</small></article>
        <article><Gauge /><span>Leader electricity scenario</span><strong>{money(analysis.leader_window_energy_cost_usd)}</strong><small>{analysis.window_days}-day facility energy at cited state industrial rate</small></article>
      </div>
    </div>

    <div className="strategy-table" role="table" aria-label="Deterministic strategy stress test">
      <div className="strategy-row strategy-row--head" role="row"><span>Investment strategy</span><span>Winner</span><span>Score</span><span>Margin</span></div>
      {analysis.strategies.map((strategy) => {
        const winner = strategy.winner_site_id ? sites.get(strategy.winner_site_id) : undefined
        return <div className={strategy.winner_site_id === analysis.leader_site_id ? 'strategy-row strategy-row--leader' : 'strategy-row'} role="row" key={strategy.name}>
          <span><strong>{strategy.name}</strong><small>{strategy.emphasis}</small></span>
          <span>{winner?.metro || 'No eligible site'}</span>
          <span>{strategy.winner_score?.toFixed(1) || '—'}</span>
          <span>{strategy.margin_to_second !== undefined ? `+${strategy.margin_to_second.toFixed(1)}` : '—'}</span>
        </div>
      })}
    </div>
    <div className="decision-case__note"><Info size={14} /><span>Selected-window comparisons use the same facility profile. Electricity spend uses attributed EIA state industrial averages and excludes negotiated tariffs, demand charges, incentives, and taxes. These are screening economics, not a financial forecast.</span></div>
  </section>
}
