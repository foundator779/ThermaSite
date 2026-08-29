import { useEffect, useRef, useState } from 'react'
import { Building2, LocateFixed, MapPin } from 'lucide-react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { CandidateSite } from '../../types/screening'

const USGS_IMAGERY_URL = 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}'
const USGS_ATTRIBUTION = 'USGS The National Map: Orthoimagery and US Topo'

function heatColor(value: number) {
  if (value >= 42) return '#ff3b1f'
  if (value >= 37) return '#ff6a35'
  if (value >= 32) return '#ff9f57'
  if (value >= 27) return '#ffd18a'
  return '#efe9dc'
}

function featureTemperature(feature?: GeoJSON.Feature) {
  const properties = feature?.properties || {}
  for (const key of ['temperature', 'Temperature', 'value', 'Value', 'tcm']) {
    const value = properties[key]
    if (typeof value === 'number') return value
  }
  return 30
}

function markerIcon(index: number, selected: boolean) {
  return L.divIcon({
    className: 'thermasite-marker-shell',
    html: `<span class="thermasite-marker${selected ? ' thermasite-marker--selected' : ''}">${index + 1}</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  })
}

function fitSites(instance: L.Map, sites: CandidateSite[]) {
  if (!sites.length) return
  const bounds = L.latLngBounds(sites.map((site) => [site.latitude, site.longitude]))
  instance.fitBounds(bounds, { padding: [70, 70], maxZoom: 5 })
}

export function ScreeningMap({ sites, selectedId, onSelect, footprint, footprintLabel }: {
  sites: CandidateSite[]
  selectedId?: string
  onSelect: (id: string) => void
  footprint?: GeoJSON.FeatureCollection
  footprintLabel?: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const candidateLayers = useRef<L.Layer[]>([])
  const footprintOverlay = useRef<L.Polygon | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string>()

  const fitAll = () => {
    if (map.current) fitSites(map.current, sites)
  }

  useEffect(() => {
    if (!host.current) return
    try {
      const instance = L.map(host.current, {
        center: [39.2, -98.5],
        zoom: 4,
        zoomControl: false,
        attributionControl: true,
      })
      L.tileLayer(USGS_IMAGERY_URL, {
        attribution: USGS_ATTRIBUTION,
        maxNativeZoom: 16,
        maxZoom: 18,
        minZoom: 3,
      }).addTo(instance)
      L.control.zoom({ position: 'bottomleft' }).addTo(instance)
      map.current = instance
      instance.whenReady(() => setReady(true))
    } catch {
      queueMicrotask(() => setError('USGS aerial imagery could not be initialized. Candidate evidence remains available.'))
    }
    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])

  useEffect(() => {
    const instance = map.current
    if (!ready || !instance) return
    candidateLayers.current.forEach((layer) => layer.removeFrom(instance))
    candidateLayers.current = []

    sites.forEach((site, index) => {
      if (site.thermal?.map_data) {
        try {
          const thermal = L.geoJSON(site.thermal.map_data, {
            style: (feature) => ({
              fillColor: heatColor(featureTemperature(feature)),
              fillOpacity: 0.64,
              color: '#090909',
              weight: 0.35,
            }),
          }).addTo(instance)
          candidateLayers.current.push(thermal)
        } catch {
          // Isolate malformed provider overlays so the remaining candidates still render.
        }
      }
      const marker = L.marker([site.latitude, site.longitude], {
        icon: markerIcon(index, site.id === selectedId),
        title: site.name,
        keyboard: true,
      }).on('click', () => onSelect(site.id)).addTo(instance)
      candidateLayers.current.push(marker)
    })
    fitSites(instance, sites)
  }, [onSelect, ready, selectedId, sites])

  useEffect(() => {
    const instance = map.current
    if (!ready || !instance || !footprint) return
    const geometry = footprint.features[0]?.geometry
    if (geometry?.type !== 'Polygon') return
    footprintOverlay.current?.removeFrom(instance)
    const paths = geometry.coordinates[0].slice(0, -1).map(([lng, lat]) => L.latLng(lat, lng))
    footprintOverlay.current = L.polygon(paths, {
      fillColor: '#ff5a36',
      fillOpacity: 0.3,
      color: '#ff6a35',
      opacity: 1,
      weight: 3,
      interactive: false,
    }).addTo(instance)
    const site = sites.find((item) => item.id === selectedId)
    if (site) instance.setView([site.latitude, site.longitude], 15, { animate: true })
  }, [footprint, ready, selectedId, sites])

  if (error) {
    return <div className="map-fallback">
      <div className="map-grid" />
      {sites.map((site, index) => <button
        key={site.id}
        className={`fallback-pin fallback-pin--${index + 1} ${selectedId === site.id ? 'active' : ''}`}
        onClick={() => onSelect(site.id)}
      ><MapPin size={15} /> {site.metro}</button>)}
      <p>{error}</p>
    </div>
  }

  return <>
    <div ref={host} className="screening-map" aria-label="Recommended facility footprint and FortyGuard heat map" />
    <div className="map-view-controls" aria-label="Map view controls">
      <button onClick={fitAll}><LocateFixed size={13} /> View all five</button>
      {footprint && <span><Building2 size={13} /> {footprintLabel || 'Generated facility footprint on industrial-edge aerial'}</span>}
    </div>
  </>
}
