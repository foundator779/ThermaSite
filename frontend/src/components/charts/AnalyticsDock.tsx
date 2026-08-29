import { useState } from 'react'
import { ArrowUpRight, ChartNoAxesCombined, Maximize2, X } from 'lucide-react'
import { artifactUrl } from '../../api/client'
import type { Artifact, ChartDefinition, RunRecord } from '../../types/run'
import { EvidencePackageCard } from '../evidence/EvidencePackageCard'
import { InteractiveChart } from './InteractiveChart'

const Placeholder = ({ label }: { label: string }) => <div className="chart-placeholder"><div className="placeholder-line"><span /><span /><span /><span /></div><p>{label}</p></div>

function findPlot(run: RunRecord | undefined, fragment: string) {
  return run?.artifacts.find((artifact) => artifact.type === 'plot' && artifact.name.toLowerCase().includes(fragment))
}

interface GraphOption {
  id: string
  title: string
  kicker: string
  artifact?: Artifact
}

export function AnalyticsDock({ run }: { run?: RunRecord }) {
  const metrics = run?.metrics || {}
  const isWetland = run?.research_spec?.habitat_type === 'everglades_wetland'
  const isCustom = run?.research_spec?.habitat_type === 'custom_habitat'
  const seasonal = ['Winter', 'Spring', 'Summer', 'Autumn'].map((season) => ({
    season: season.slice(0, 3),
    value: typeof metrics[`${season.toLowerCase()}_trend_c_per_decade`] === 'number' ? metrics[`${season.toLowerCase()}_trend_c_per_decade`] as number : 0,
  }))
  const hasSeasonal = seasonal.some((item) => item.value !== 0)
  const graphs: GraphOption[] = isCustom ? [
    { id: 'area-temperature', title: 'Area temperature', kicker: 'Trend & significance', artifact: findPlot(run, 'area temperature') },
    { id: 'area-precipitation', title: 'Area precipitation', kicker: 'Habitat climate pressure', artifact: findPlot(run, 'area precipitation') },
    { id: 'source-agreement', title: 'Source agreement', kicker: 'Independent corroboration', artifact: findPlot(run, 'climate source agreement') },
    { id: 'species-observations', title: 'Species observations', kicker: 'Species & biodiversity', artifact: findPlot(run, 'biodiversity observations') },
    { id: 'fire-wetlands', title: 'Fire & wetlands', kicker: 'Disturbance context', artifact: findPlot(run, 'wildfire wetlands') },
    { id: 'vegetation-condition', title: 'Vegetation condition', kicker: 'Sentinel-2 seasonal intelligence' },
  ] : isWetland ? [
    { id: 'annual-water-level', title: 'Annual water level', kicker: 'Hydrologic trend', artifact: findPlot(run, 'annual water level') },
    { id: 'habitat-pressure', title: 'Habitat pressure', kicker: 'Baseline comparison', artifact: findPlot(run, 'wetland habitat pressure') },
    { id: 'precipitation-water', title: 'Precipitation & water', kicker: 'Paired association', artifact: findPlot(run, 'precipitation water level association') },
  ] : [
    { id: 'annual-temperature', title: 'Annual temperature', kicker: 'Trend & significance', artifact: findPlot(run, 'annual temperature') },
    { id: 'seasonal-change', title: 'Seasonal change', kicker: 'Regional comparison', artifact: findPlot(run, 'seasonal change') },
    { id: 'temperature-sea-ice', title: 'Temperature & sea ice', kicker: 'Paired association', artifact: findPlot(run, 'association') },
  ]
  const [selectedGraphId, setSelectedGraphId] = useState(graphs[0].id)
  const [expanded, setExpanded] = useState(false)
  const selectedGraph = graphs.find((graph) => graph.id === selectedGraphId) || graphs[0]
  const seasonalFallback: ChartDefinition | undefined = hasSeasonal ? {
    kind: 'bar', data: seasonal, x_key: 'season', x_label: 'Season', y_label: 'Trend', unit: '°C/decade',
    series: [{ key: 'value', label: 'Temperature trend', color: '#2c8265', kind: 'bar' }],
  } : undefined
  const interactiveData = run?.chart_data?.[selectedGraph.id] || (selectedGraph.id === 'seasonal-change' ? seasonalFallback : undefined)
  const graphVisual = (large = false) => interactiveData
    ? interactiveData.data.length
      ? <InteractiveChart definition={interactiveData} large={large} />
      : <Placeholder label="No validated data points were returned for this indicator" />
    : selectedGraph.artifact
      ? <img className={large ? 'graph-image--large' : undefined} src={artifactUrl(selectedGraph.artifact.download_url)} alt={selectedGraph.title} />
      : <Placeholder label="Generated analysis will appear here" />

  return <><section className="analytics-dock" aria-label="Analysis and evidence bottom bar">
    <article className="analytics-card analytics-card--viewer">
      <header>
        <div><span className="eyebrow">{selectedGraph.kicker}</span><h3>{selectedGraph.title}</h3></div>
        <div className="graph-card-controls">
          <label><ChartNoAxesCombined size={14} /><span>View graph</span><select aria-label="Select analysis graph" value={selectedGraph.id} onChange={(event) => setSelectedGraphId(event.target.value)}>{graphs.map((graph) => <option key={graph.id} value={graph.id}>{graph.title}</option>)}</select></label>
          <button className="graph-expand-button" type="button" aria-label={`Expand ${selectedGraph.title} graph`} onClick={() => setExpanded(true)}><Maximize2 size={15} /></button>
          {selectedGraph.artifact && <a href={artifactUrl(selectedGraph.artifact.download_url)} target="_blank" rel="noreferrer" aria-label={`Open ${selectedGraph.title}`}><ArrowUpRight size={16} /></a>}
        </div>
      </header>
      {graphVisual()}
    </article>
    <div className="evidence-dock-slot"><EvidencePackageCard run={run} /></div>
  </section>
  {expanded && <div className="graph-viewer-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setExpanded(false) }}>
    <section className="graph-viewer-dialog" role="dialog" aria-modal="true" aria-label={`${selectedGraph.title} expanded graph`}>
      <header><div><span className="eyebrow">{selectedGraph.kicker}</span><h2>{selectedGraph.title}</h2>{Boolean(interactiveData?.data.length) && <p>Hover for exact values · drag the range selector to zoom · drag the lower-right corner to resize</p>}</div><button className="icon-button" type="button" aria-label="Close expanded graph" onClick={() => setExpanded(false)}><X size={20} /></button></header>
      <div className="expanded-graph-visual">{graphVisual(true)}</div>
    </section>
  </div>}
  </>
}
