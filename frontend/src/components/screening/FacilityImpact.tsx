import { Activity, Building2, Droplets, Gauge, Info, Zap } from 'lucide-react'
import type { CandidateSite, ResourceEstimate, SiteRecommendation } from '../../types/screening'

function compact(value: number, unit: string) {
  return `${new Intl.NumberFormat('en-US', {
    maximumFractionDigits: value >= 1000 ? 0 : 1,
    notation: value >= 1_000_000 ? 'compact' : 'standard',
  }).format(value)} ${unit}`
}

export function FacilityImpact({ site, estimate, recommendation }: {
  site?: CandidateSite
  estimate?: ResourceEstimate
  recommendation?: SiteRecommendation
}) {
  return <section className="impact-section" id="impact">
    <header className="impact-heading">
      <div><span className="eyebrow"><Activity size={13} /> FortyGuard facility projection</span><h2>See the facility before you commit.</h2><p>Every finalist receives the same physical footprint and operating profile on an edge-market industrial search zone. FortyGuard supplies ambient heat at that illustrative AOI; transparent PUE and WUE assumptions translate it into a comparable resource scenario—not proof that a parcel is vacant, available, zoned, or serviceable.</p></div>
      <span className="estimate-badge">Planning estimate · not engineering</span>
    </header>
    {estimate && site ? <div className="impact-shell">
      <div className="impact-site">
        <span className="impact-rank">#{recommendation?.rank || '—'} recommended market</span>
        <h3>{site.metro}, {site.state}</h3>
        <p>{site.shortlist_reason || 'Selected by the agent for full thermal and infrastructure diligence.'}</p>
        <dl>
          <div><dt>Generated campus</dt><dd>{estimate.area_acres.toFixed(1)} acres</dd></div>
          <div><dt>Planning density</dt><dd>{estimate.it_density_mw_per_acre?.toFixed(2) || '—'} MW/acre</dd></div>
          <div><dt>FortyGuard mean</dt><dd>{estimate.thermal.mean_temperature_c.toFixed(1)}°C</dd></div>
          <div><dt>Scenario confidence</dt><dd>{Math.round(estimate.confidence * 100)}%</dd></div>
        </dl>
      </div>
      <div className="impact-metrics">
        <article><Building2 /><span>Planned IT capacity</span><strong>{estimate.it_load_mw.toFixed(1)} MW</strong><small>Acreage × design density</small></article>
        <article><Zap /><span>Average facility power</span><strong>{estimate.average_facility_power_mw.toFixed(1)} MW</strong><small>Peak service {estimate.peak_facility_power_mw.toFixed(1)} MW</small></article>
        <article><Droplets /><span>July direct water</span><strong>{compact(estimate.window_water_gallons_low, 'gal')}–{compact(estimate.window_water_gallons_high, 'gal')}</strong><small>WUE {estimate.wue_l_kwh_low}–{estimate.wue_l_kwh_high} L/kWh</small></article>
        <article><Gauge /><span>Heat-adjusted PUE</span><strong>{estimate.heat_adjusted_pue.toFixed(3)}</strong><small>{compact(estimate.window_facility_energy_mwh, 'MWh')} in selected window</small></article>
      </div>
      <div className="impact-proof"><Info size={15} /><span>FortyGuard activities <strong>{estimate.thermal.activity_ids.join(' · ')}</strong>. Facility energy = IT energy × heat-adjusted PUE. Direct water = IT energy × cooling-system WUE range.</span></div>
    </div> : <div className="impact-pending"><Activity size={24} /><strong>Facility projections arrive with the heat analysis.</strong><span>Sites without FortyGuard evidence remain visible but cannot receive a resource projection or final rank.</span></div>}
  </section>
}
