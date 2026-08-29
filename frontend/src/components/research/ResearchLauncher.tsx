import { ArrowRight, MapPin, Sparkles } from 'lucide-react'
import { useState } from 'react'
import type { StudyArea } from '../../types/run'

export const CANONICAL_PROMPT = 'How has this habitat changed from 2005–2025? Assess climate trends, documented species and biodiversity, wildfire exposure, and wetlands using independent authoritative evidence.'

export function ResearchLauncher({ studyArea, onRun, loading }: { studyArea?: StudyArea; onRun: (query: string, area: StudyArea) => void; loading: boolean }) {
  const [query, setQuery] = useState(CANONICAL_PROMPT)
  const areaValid = Boolean(studyArea && studyArea.area_sq_mi > 0 && studyArea.area_sq_mi <= 150)
  return <section className="research-launcher" aria-labelledby="launcher-title">
    <div className="launcher-kicker"><Sparkles size={14} /> Autonomous research workspace</div>
    <h1 id="launcher-title">Launch a habitat investigation.</h1>
    <p>Draw a circle or polygon, then investigate climate, species, wildfire, and wetlands.</p>
    <div className={`selected-area-chip ${areaValid ? 'selected-area-chip--ready' : ''}`}><MapPin size={14} /><span>{studyArea ? `${studyArea.shape === 'circle' ? 'Circle' : 'Polygon'} · ${studyArea.area_sq_mi.toFixed(1)} mi²` : 'Draw a study area on the map'}</span></div>
    <textarea aria-label="Climate research question" value={query} onChange={(event) => setQuery(event.target.value)} rows={4} />
    <div className="launcher-footer">
      <button className="primary-button" disabled={loading || !areaValid || query.trim().length < 12} onClick={() => studyArea && onRun(query, studyArea)}>
        {loading ? 'Creating run…' : 'Run research'} <ArrowRight size={16} />
      </button>
    </div>
  </section>
}
