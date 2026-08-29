import { ArrowUpRight, Bot, CheckCircle2, Database, FileCode2, GitBranch, ShieldCheck, X } from 'lucide-react'
import { artifactUrl } from '../../api/client'
import type { EvidenceChain, EvidenceNode, ModelUsageRecord } from '../../types/run'

const kindLabels: Record<EvidenceNode['kind'], string> = {
  claim: 'Finding',
  metric: 'Structured metric',
  dataset: 'Authoritative source',
  transformation: 'Transformation',
  code: 'Executed code',
  validation: 'Scientific check',
  artifact: 'Reproducibility artifact',
}

function NodeIcon({ kind }: { kind: EvidenceNode['kind'] }) {
  if (kind === 'dataset') return <Database size={17} />
  if (kind === 'code') return <FileCode2 size={17} />
  if (kind === 'validation') return <ShieldCheck size={17} />
  if (kind === 'claim') return <CheckCircle2 size={17} />
  return <GitBranch size={17} />
}

export function EvidenceDrawer({ evidence, models, loading, error, onClose }: {
  evidence?: EvidenceChain
  models?: ModelUsageRecord[]
  loading: boolean
  error?: Error | null
  onClose: () => void
}) {
  const labels = new Map(evidence?.nodes.map((node) => [node.id, node.label]))
  return <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
    <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title" onMouseDown={(event) => event.stopPropagation()}>
      <header>
        <div><span className="eyebrow"><GitBranch size={14} /> Scientific chain of custody</span><h2 id="evidence-title">Evidence behind the finding</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="Close evidence inspector"><X size={19} /></button>
      </header>
      {loading && <div className="drawer-message">Building the evidence graph…</div>}
      {error && <div className="drawer-message drawer-message--error">Unable to load evidence: {error.message}</div>}
      {evidence && <>
        <div className={`validation-strip validation-strip--${evidence.validation_status}`}><ShieldCheck size={16} /><div><strong>{evidence.validation_status === 'validated' ? 'Scientific validation passed' : 'Validation is incomplete'}</strong><span>Every visible relationship comes from persisted run state.</span></div></div>
        <section className="claim-panel"><span>Final claim</span><p>{evidence.claim}</p></section>
        <section className="ai-provenance"><h3><Bot size={16} /> Google AI provenance</h3><p>Each model has a distinct, bounded role. Generative media is never scientific evidence.</p><div>{models?.map((model) => <article key={model.family}><span className={`model-status model-status--${model.status}`}>{model.status}</span><strong>{model.family}</strong><code>{model.model}</code><small>{model.purpose}</small>{model.invocation_count > 0 && <em>{model.invocation_count} verified invocation{model.invocation_count === 1 ? '' : 's'}</em>}</article>)}</div></section>
        <section className="evidence-node-list" aria-label="Evidence nodes">
          {evidence.nodes.filter((node) => node.kind !== 'claim').map((node) => <article className={`evidence-node evidence-node--${node.kind}`} key={node.id}>
            <div className="evidence-node__icon"><NodeIcon kind={node.kind} /></div>
            <div><span>{kindLabels[node.kind]}</span><strong>{node.label}</strong><p>{node.detail}</p>{node.sha256 && <code>SHA-256 {node.sha256.slice(0, 16)}…</code>}</div>
            {node.uri && !node.uri.startsWith('file://') && <a href={artifactUrl(node.uri)} target="_blank" rel="noreferrer" aria-label={`Open ${node.label}`}><ArrowUpRight size={15} /></a>}
          </article>)}
        </section>
        <section className="evidence-relations"><h3>Recorded relationships</h3>{evidence.links.map((link, index) => <div key={`${link.source}-${link.target}-${index}`}><strong>{labels.get(link.source) || link.source}</strong><span>{link.relationship}</span><strong>{labels.get(link.target) || link.target}</strong></div>)}</section>
      </>}
    </aside>
  </div>
}
