import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileChartColumn, Film, GitBranch, Link2, LoaderCircle, Play } from 'lucide-react'
import { artifactUrl } from '../../api/client'
import { generateBriefingVideo, getModelUsage } from '../../api/runs'
import { getEvidence } from '../../api/missions'
import type { RunRecord } from '../../types/run'
import { EvidenceDrawer } from './EvidenceDrawer'
import { BriefingVideoDialog } from './BriefingVideoDialog'

export function EvidencePackageCard({ run }: { run?: RunRecord }) {
  const [open, setOpen] = useState(false)
  const [videoOpen, setVideoOpen] = useState(false)
  const queryClient = useQueryClient()
  const bundle = run?.artifacts.find((artifact) => artifact.type === 'bundle')
  const video = run?.artifacts.find((artifact) => artifact.type === 'video')
  const videoPending = ['QUEUED', 'GENERATING'].includes(run?.briefing_video_status || '')
  const generateVideo = useMutation({
    mutationFn: () => generateBriefingVideo(run!.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', run?.id] }),
  })
  const evidence = useQuery({
    queryKey: ['evidence', run?.id],
    queryFn: () => getEvidence(run!.id),
    enabled: open && Boolean(run?.id),
  })
  const modelUsage = useQuery({
    queryKey: ['model-usage', run?.id],
    queryFn: () => getModelUsage(run!.id),
    enabled: open && Boolean(run?.id),
  })

  return <article className="evidence-card">
    <div className="evidence-icon"><FileChartColumn size={18} /></div>
    <div className="evidence-card__body"><span className="eyebrow">Evidence package</span><h3>{run?.status === 'COMPLETED' ? 'Reproducible by design' : 'Provenance is building'}</h3><p>Sources, hashes, transformations, code, attempts, and validation remain linked to every result.</p>{run?.operational_impact?.estimated_manual_hours_saved && <p className="impact-note">Automated {run.operational_impact.workflow_steps_automated} steps · approximately {run.operational_impact.estimated_manual_hours_saved} analyst hours saved</p>}</div>
    <div className="evidence-actions">
      <span><Link2 size={13} /> {run?.artifacts.length || 0} linked artifacts</span>
      {run?.status === 'COMPLETED' && <button className="secondary-button" onClick={() => setOpen(true)}><GitBranch size={15} /> Inspect evidence</button>}
      {bundle ? <a className="download-button" href={artifactUrl(bundle.download_url)}><Download size={15} /> Download bundle</a> : <button className="download-button" disabled><Download size={15} /> Bundle pending</button>}
      {run?.status === 'COMPLETED' && <div className="briefing-control">
        <div><Film size={15} /><span><strong>Veo field briefing</strong><small>AI visual · illustrative only</small></span></div>
        {video && run.briefing_video_status === 'COMPLETED'
          ? <button className="briefing-button" onClick={() => setVideoOpen(true)}><Play size={14} /> Watch</button>
          : <button className="briefing-button" disabled={videoPending || generateVideo.isPending} onClick={() => generateVideo.mutate()}>
            {videoPending || generateVideo.isPending ? <LoaderCircle className="spin" size={14} /> : <Film size={14} />}
            {videoPending || generateVideo.isPending ? 'Generating…' : run.briefing_video_status === 'FAILED' ? 'Retry video' : 'Generate video'}
          </button>}
      </div>}
      {(generateVideo.error || run?.briefing_video_error) && <p className="card-error briefing-error">{generateVideo.error?.message || run?.briefing_video_error}</p>}
    </div>
    {open && <EvidenceDrawer evidence={evidence.data} models={modelUsage.data?.models} loading={evidence.isLoading || modelUsage.isLoading} error={evidence.error || modelUsage.error} onClose={() => setOpen(false)} />}
    {videoOpen && run && video && <BriefingVideoDialog run={run} artifact={video} onClose={() => setVideoOpen(false)} />}
  </article>
}
