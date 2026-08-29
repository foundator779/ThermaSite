import { ExternalLink, FileArchive, FileText, X } from 'lucide-react'
import { API_BASE, getSessionToken } from '../../api/client'
import type { ScreeningRecord } from '../../types/screening'

export function EvidenceDrawer({ record, open, onClose }: {
  record?: ScreeningRecord
  open: boolean
  onClose: () => void
}) {
  if (!open || !record) return null
  const download = async (artifact: ScreeningRecord['artifacts'][number]) => {
    const token = getSessionToken()
    const response = await fetch(`${API_BASE}/api/v1/screenings/${record.id}/artifacts/${artifact.id}`, {
      credentials: 'omit', headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) return
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.name
    anchor.click()
    URL.revokeObjectURL(url)
  }
  const citations = record.candidates.flatMap((site) => site.citations.map((citation) => ({ site: site.name, ...citation })))
  return <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
    <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><span className="eyebrow">Decision provenance</span><h2 id="evidence-title">Evidence & exports</h2></div><button onClick={onClose} aria-label="Close evidence"><X /></button></header>
      <section className="audit-card">
        <span>{record.audit?.passed ? 'Audit passed' : 'Audit pending'}</span>
        <p>{record.audit?.summary || 'Evidence audit will run after deterministic scoring.'}</p>
        {record.audit?.warnings.map((warning) => <small key={warning}>{warning}</small>)}
      </section>
      <section><h3>Download package</h3><div className="artifact-list">
        {record.artifacts.map((artifact) => <button key={artifact.id} onClick={() => download(artifact)}>
          {artifact.content_type === 'application/zip' ? <FileArchive /> : <FileText />}
          <span><strong>{artifact.name}</strong><small>{Math.max(1, Math.round(artifact.size_bytes / 1024))} KB</small></span>
        </button>)}
        {!record.artifacts.length && <p>Artifacts appear after the recommendation is audited.</p>}
      </div></section>
      <section><h3>Cited sources</h3><div className="citation-list">
        {citations.map((citation, index) => <a href={citation.url} target="_blank" rel="noreferrer" key={`${citation.url}-${index}`}>
          <span><b>{citation.site}</b><strong>{citation.title}</strong><small>{citation.fact}</small></span><ExternalLink size={15} />
        </a>)}
      </div></section>
      <footer>ThermaSite screens relative investment risk. Verify permits, grid capacity, water rights, and engineering assumptions before acting.</footer>
    </aside>
  </div>
}
