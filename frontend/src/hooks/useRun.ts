import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../api/client'
import { getRun } from '../api/runs'
import type { RunEvent } from '../types/run'

export function useRun(runId?: string) {
  const queryClient = useQueryClient()
  const [stream, setStream] = useState<{ runId?: string; events: RunEvent[] }>({ events: [] })
  const seen = useRef<{ runId?: string; ids: Set<string> }>({ ids: new Set() })
  const query = useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: ({ state }) => {
      const status = state.data?.status
      const briefingStatus = state.data?.briefing_video_status
      if (briefingStatus && ['QUEUED', 'GENERATING'].includes(briefingStatus)) return 3000
      return status && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(status) ? false : 3000
    },
  })

  useEffect(() => {
    if (!runId) return
    if (seen.current.runId !== runId) seen.current = { runId, ids: new Set() }
    const source = new EventSource(`${API_BASE}/api/v1/runs/${runId}/events`)
    const receive = (message: MessageEvent) => {
      const event = JSON.parse(message.data) as RunEvent
      if (seen.current.ids.has(event.id)) return
      seen.current.ids.add(event.id)
      setStream((current) => current.runId === runId
        ? { runId, events: [...current.events, event] }
        : { runId, events: [event] })
      if (['run.completed', 'run.failed', 'bundle.completed', 'briefing.video.completed', 'briefing.video.failed'].includes(event.type)) {
        queryClient.invalidateQueries({ queryKey: ['run', runId] })
      }
    }
    const eventNames = ['run.created', 'adk.coordination.completed', 'research.parsed', 'research.scope_expanded', 'dataset.candidate', 'dataset.selected', 'acquisition.started', 'acquisition.completed', 'validation.completed', 'harmonization.completed', 'analysis.plan_created', 'demo.fault.injected', 'code.generated', 'execution.started', 'execution.failed', 'repair.started', 'repair.completed', 'execution.completed', 'evidence.disagreement.detected', 'evidence.corroboration.completed', 'adk.scientific_review.completed', 'scientific_validation.completed', 'report.completed', 'bundle.completed', 'monitoring.mission.created', 'monitoring.policy.updated', 'monitoring.check.started', 'adk.operational_action.completed', 'monitoring.comparison.completed', 'monitoring.alert.delivery_recorded', 'briefing.video.queued', 'briefing.video.generating', 'briefing.video.completed', 'briefing.video.failed', 'run.completed', 'run.failed']
    eventNames.forEach((name) => source.addEventListener(name, receive))
    return () => source.close()
  }, [runId, queryClient])

  const streamEvents = stream.runId === runId ? stream.events : []
  const merged = [...(query.data?.events || []), ...streamEvents].filter(
    (event, index, events) => events.findIndex((item) => item.id === event.id) === index,
  )
  return { ...query, events: merged }
}
