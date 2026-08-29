import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE, getSessionToken } from '../api/client'
import { getScreening } from '../api/screenings'
import type { ScreeningEvent } from '../types/screening'

const TERMINAL = ['COMPLETED', 'FAILED', 'CANCELLED']

export function useScreening(screeningId?: string) {
  const queryClient = useQueryClient()
  const [eventState, setEventState] = useState<{ screeningId?: string; items: ScreeningEvent[] }>({ items: [] })
  const seen = useRef(new Set<string>())
  const query = useQuery({
    queryKey: ['screening', screeningId],
    queryFn: () => getScreening(screeningId!),
    enabled: Boolean(screeningId),
    refetchInterval: ({ state }) => TERMINAL.includes(state.data?.status || '') ? false : 2500,
  })

  useEffect(() => {
    seen.current = new Set()
    if (!screeningId) return
    const controller = new AbortController()
    const receive = (event: ScreeningEvent) => {
      if (seen.current.has(event.id)) return
      seen.current.add(event.id)
      setEventState((current) => ({
        screeningId,
        items: current.screeningId === screeningId ? [...current.items, event] : [event],
      }))
      queryClient.invalidateQueries({ queryKey: ['screening', screeningId] })
    }
    const stream = async () => {
      const token = getSessionToken()
      const response = await fetch(`${API_BASE}/api/v1/screenings/${screeningId}/events`, {
        credentials: 'omit', signal: controller.signal,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!response.ok || !response.body) return
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) {
          const data = block.split('\n').find((line) => line.startsWith('data: '))
          if (data) receive(JSON.parse(data.slice(6)) as ScreeningEvent)
        }
      }
    }
    stream().catch((error) => { if (error.name !== 'AbortError') return })
    return () => controller.abort()
  }, [queryClient, screeningId])

  const liveEvents = eventState.screeningId === screeningId ? eventState.items : []
  const merged = [...(query.data?.events || []), ...liveEvents].filter(
    (event, index, all) => all.findIndex((item) => item.id === event.id) === index,
  )
  return { ...query, events: merged }
}
