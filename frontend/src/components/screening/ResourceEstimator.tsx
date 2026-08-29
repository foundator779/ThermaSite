import { Activity, ArrowRight, Droplets, Gauge, Info, PenTool, Zap } from 'lucide-react'
import type { CandidateSite, CoolingSystem, ResourceEstimate, ResourceEstimatorInput } from '../../types/screening'

function compact(value: number, unit: string) {
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: value >= 1000 ? 0 : 1, notation: value >= 1_000_000 ? 'compact' : 'standard' }).format(value)} ${unit}`
}

function sampleFootprint(site: CandidateSite): GeoJSON.FeatureCollection {
  const halfSideMiles = 0.125 // 40 acres (0.0625 mi²)
  const lat = halfSideMiles / 69
  const lng = halfSideMiles / (69.172 * Math.cos(site.latitude * Math.PI / 180))
  const ring = [
    [site.longitude - lng, site.latitude - lat], [site.longitude + lng, site.latitude - lat],
    [site.longitude + lng, site.latitude + lat], [site.longitude - lng, site.latitude + lat],
    [site.longitude - lng, site.latitude - lat],
  ]
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { sample: true }, geometry: { type: 'Polygon', coordinates: [ring] } }] }
}

export function ResourceEstimator({
  site, footprint, areaAcres, latest, input, pending, error,
  onFootprintChange, onInputChange, onEstimate,
}: {
  site?: CandidateSite
  footprint?: GeoJSON.FeatureCollection
  areaAcres: number
  latest?: ResourceEstimate
  input: Omit<ResourceEstimatorInput, 'site_id' | 'polygon'>
  pending: boolean
  error?: Error | null
  onFootprintChange: (polygon: GeoJSON.FeatureCollection, acres: number) => void
  onInputChange: (next: Omit<ResourceEstimatorInput, 'site_id' | 'polygon'>) => void
  onEstimate: () => void
}) {
  const active = latest
  return <section className="estimator-section" id="estimator">
    <header className="estimator-heading">
      <div><span className="eyebrow"><Activity size={13} /> FortyGuard resource estimator</span><h2>Draw the campus. Stress-test the load.</h2><p>Translate a proposed footprint and IT load into transparent power and direct-water scenarios. Area defines the FortyGuard AOI—it does not invent capacity.</p></div>
      <span className="estimate-badge">Estimator · not engineering</span>
    </header>
    <div className="estimator-grid">
      <div className="estimator-form">
        <div className="footprint-status">
          <PenTool size={19} />
          <span><small>Proposed footprint</small><strong>{footprint ? `${areaAcres.toFixed(1)} acres drawn` : 'Draw on the map above'}</strong></span>
          {!footprint && site && <button onClick={() => onFootprintChange(sampleFootprint(site), 40)}>Use 40-acre sample</button>}
        </div>
        <div className="estimate-inputs">
          <label><span>IT capacity, MW</span><input aria-label="IT capacity, MW" type="number" min="1" max="1000" value={input.it_load_mw} onChange={(event) => onInputChange({ ...input, it_load_mw: Number(event.target.value) })} /></label>
          <label><span>Utilization, %</span><input aria-label="Utilization, %" type="number" min="1" max="100" value={Math.round(input.utilization * 100)} onChange={(event) => onInputChange({ ...input, utilization: Number(event.target.value) / 100 })} /></label>
          <label><span>Baseline PUE</span><input aria-label="Baseline PUE" type="number" min="1" max="3" step="0.01" value={input.baseline_pue} onChange={(event) => onInputChange({ ...input, baseline_pue: Number(event.target.value) })} /></label>
          <label><span>Cooling architecture</span><select aria-label="Cooling architecture" value={input.cooling_system} onChange={(event) => onInputChange({ ...input, cooling_system: event.target.value as CoolingSystem })}><option value="dry">Dry / air</option><option value="evaporative">Evaporative</option><option value="hybrid">Hybrid</option><option value="liquid">Liquid</option></select></label>
        </div>
        <div className="formula-note"><Info size={14} /><span>Facility energy = IT energy × heat-adjusted PUE. Direct water = IT energy × cooling-system WUE range. FortyGuard supplies the footprint’s ambient heat evidence.</span></div>
        <button className="primary-action estimate-action" disabled={!site || !footprint || pending} onClick={onEstimate}>{pending ? 'FortyGuard is analyzing…' : 'Estimate power & water'} <ArrowRight size={16} /></button>
        {error && <p className="inline-error">{error.message}</p>}
      </div>
      <div className="estimate-results" aria-live="polite">
        {active ? <>
          <div className="estimate-result-head"><span><strong>{site?.metro}</strong><small>{active.area_acres.toFixed(1)} acres · {active.cooling_system} cooling · {Math.round(active.confidence * 100)}% scenario confidence</small></span><b>{active.thermal.mean_temperature_c.toFixed(1)}°C mean</b></div>
          <div className="estimate-metrics">
            <article><Zap /><span>Average facility power</span><strong>{active.average_facility_power_mw.toFixed(1)} MW</strong><small>Peak {active.peak_facility_power_mw.toFixed(1)} MW</small></article>
            <article><Gauge /><span>Selected-window energy</span><strong>{compact(active.window_facility_energy_mwh, 'MWh')}</strong><small>Heat-adjusted PUE {active.heat_adjusted_pue.toFixed(3)}</small></article>
            <article><Droplets /><span>Direct water range</span><strong>{compact(active.window_water_gallons_low, 'gal')}–{compact(active.window_water_gallons_high, 'gal')}</strong><small>WUE {active.wue_l_kwh_low}–{active.wue_l_kwh_high} L/kWh</small></article>
          </div>
          <div className="annual-scenario"><span>Illustrative annual extrapolation</span><strong>{compact(active.illustrative_annual_energy_mwh, 'MWh')} · {compact(active.illustrative_annual_water_gallons_low, 'gal')}–{compact(active.illustrative_annual_water_gallons_high, 'gal')}</strong><small>Assumes the selected July heat window persists all year; disabled as a ranking input.</small></div>
          <details><summary>Assumptions & limitations</summary><ul>{active.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul><p>{active.disclaimer}</p></details>
        </> : <div className="estimate-empty"><Activity size={24} /><strong>No resource scenario yet.</strong><span>Draw a footprint, set the operating assumptions, and run the FortyGuard estimator.</span></div>}
      </div>
    </div>
  </section>
}
