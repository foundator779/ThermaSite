import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, BadgeCheck, Database, Grid3X3, Search } from 'lucide-react'
import { listDatasets } from '../../api/datasets'

const roleNames: Record<string, string> = {
  local_station_temperature: 'Local station',
  regional_gridded_temperature: 'Regional temperature',
  nearby_sea_ice: 'Sea-ice evidence',
  area_station_climate: 'Selected-area stations',
  area_regional_climate: 'Selected-area regional climate',
  species_biodiversity: 'Species & biodiversity',
  wildfire_activity: 'Wildfire activity',
  wetland_inventory: 'Wetland inventory',
}

export function DatasetsView() {
  const [search, setSearch] = useState('')
  const query = useQuery({ queryKey: ['datasets'], queryFn: listDatasets, staleTime: 60_000 })
  const datasets = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (query.data?.datasets || []).filter((dataset) => !needle || [dataset.name, dataset.provider, dataset.data_role, dataset.rationale].some((value) => value.toLowerCase().includes(needle)))
  }, [query.data, search])

  return <section className="library-page" aria-labelledby="datasets-title">
    <div className="library-hero">
      <div><span className="eyebrow"><Database size={14} /> Climate knowledge registry</span><h1 id="datasets-title">Authoritative datasets</h1><p>Explore the source catalog HabiWatch can select for autonomous analysis.</p></div>
      {query.data && <div className="registry-version"><BadgeCheck size={19} /><span>Registry version<strong>{query.data.registry_version}</strong></span></div>}
    </div>
    <div className="library-toolbar">
      <label className="library-search"><Search size={18} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search datasets or providers" /></label>
      <span>{datasets.length} authoritative sources</span>
    </div>

    {query.isLoading && <div className="library-message">Loading dataset registry…</div>}
    {query.isError && <div className="library-message library-message--error">Unable to load datasets: {query.error.message}</div>}
    {!query.isLoading && !query.isError && datasets.length === 0 && <div className="library-empty"><Database size={28} /><h2>No datasets found</h2><p>Try a broader provider, role, or source name.</p></div>}

    <div className="dataset-grid">
      {datasets.map((dataset) => <article className="dataset-card" key={dataset.dataset_id}>
        <div className="dataset-card__header"><span className="dataset-icon"><Database size={20} /></span><span className="authority-badge"><BadgeCheck size={14} /> {Math.round(dataset.authority_score * 100)}% authority</span></div>
        <span className="dataset-role">{roleNames[dataset.data_role] || dataset.data_role.replaceAll('_', ' ')}</span>
        <h2>{dataset.name}</h2>
        <p className="dataset-provider">{dataset.provider}</p>
        <p className="dataset-rationale">{dataset.rationale}</p>
        <dl><div><dt>Temporal</dt><dd>{dataset.temporal_resolution}</dd></div><div><dt>Spatial</dt><dd>{dataset.spatial_resolution}</dd></div><div><dt>Dataset ID</dt><dd>{dataset.dataset_id}</dd></div></dl>
        <a href={dataset.documentation_url} target="_blank" rel="noreferrer">View source documentation <ArrowUpRight size={16} /></a>
      </article>)}
    </div>
    <div className="registry-note"><Grid3X3 size={18} /><p><strong>Role-aware selection</strong> HabiWatch combines complementary datasets when one source cannot answer the complete scientific question.</p></div>
  </section>
}
