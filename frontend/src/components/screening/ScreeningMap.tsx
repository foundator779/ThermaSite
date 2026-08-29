import { useEffect, useRef, useState } from 'react'
import { Building2, LocateFixed, MapPin } from 'lucide-react'
import { loadGoogleMaps } from '../../api/googleMaps'
import { runtimeGoogleMapsApiKey } from '../../api/runtimeConfig'
import type { CandidateSite } from '../../types/screening'

function heatColor(value: number) {
  if (value >= 42) return '#ff3b1f'
  if (value >= 37) return '#ff6a35'
  if (value >= 32) return '#ff9f57'
  if (value >= 27) return '#ffd18a'
  return '#efe9dc'
}

function featureTemperature(feature: google.maps.Data.Feature) {
  for (const key of ['temperature', 'Temperature', 'value', 'Value', 'tcm']) {
    const value = feature.getProperty(key)
    if (typeof value === 'number') return value
  }
  return 30
}

export function ScreeningMap({ sites, selectedId, onSelect, footprint, footprintLabel }: {
  sites: CandidateSite[]
  selectedId?: string
  onSelect: (id: string) => void
  footprint?: GeoJSON.FeatureCollection
  footprintLabel?: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<google.maps.Map | null>(null)
  const markers = useRef<google.maps.Marker[]>([])
  const footprintOverlay = useRef<google.maps.Polygon | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string>()

  const fitAll = () => {
    if (!map.current || !sites.length) return
    const bounds = new google.maps.LatLngBounds()
    sites.forEach((site) => bounds.extend({ lat: site.latitude, lng: site.longitude }))
    map.current.fitBounds(bounds, 70)
  }

  useEffect(() => {
    if (!host.current || !runtimeGoogleMapsApiKey) return
    let active = true
    loadGoogleMaps(runtimeGoogleMapsApiKey)
      .then(() => {
        if (!active || !host.current) return
        map.current = new google.maps.Map(host.current, {
          center: { lat: 39.2, lng: -98.5 },
          zoom: 4,
          mapTypeId: google.maps.MapTypeId.HYBRID,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          clickableIcons: false,
          backgroundColor: '#111111',
          styles: [
            { elementType: 'geometry', stylers: [{ color: '#181818' }] },
            { elementType: 'labels.text.stroke', stylers: [{ color: '#181818' }] },
            { elementType: 'labels.text.fill', stylers: [{ color: '#8a8a84' }] },
            { featureType: 'administrative', elementType: 'geometry', stylers: [{ color: '#3a3a36' }] },
            { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#292927' }] },
            { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#090909' }] },
            { featureType: 'poi', stylers: [{ visibility: 'off' }] },
          ],
        })
        setReady(true)
      })
      .catch(() => setError('Google Maps could not be loaded. Candidate evidence remains available.'))
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!ready || !map.current) return
    markers.current.forEach((marker) => marker.setMap(null))
    markers.current = []
    map.current.data.forEach((feature) => map.current?.data.remove(feature))
    const bounds = new google.maps.LatLngBounds()
    sites.forEach((site, index) => {
      const position = { lat: site.latitude, lng: site.longitude }
      bounds.extend(position)
      const marker = new google.maps.Marker({
        map: map.current,
        position,
        label: { text: String(index + 1), color: '#090909', fontWeight: '800' },
        title: site.name,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          fillColor: site.id === selectedId ? '#ff5a36' : '#f3f1ea',
          fillOpacity: 1,
          strokeColor: '#090909',
          strokeWeight: 3,
          scale: site.id === selectedId ? 12 : 10,
        },
      })
      marker.addListener('click', () => onSelect(site.id))
      markers.current.push(marker)
      if (site.thermal?.map_data) {
        try { map.current?.data.addGeoJson(site.thermal.map_data) } catch { /* isolate malformed provider overlays */ }
      }
    })
    map.current.data.setStyle((feature) => ({
      fillColor: heatColor(featureTemperature(feature)),
      fillOpacity: 0.64,
      strokeColor: '#090909',
      strokeWeight: 0.35,
    }))
    if (sites.length) map.current.fitBounds(bounds, 70)
  }, [onSelect, ready, selectedId, sites])

  useEffect(() => {
    if (!ready || !map.current || !footprint) return
    const geometry = footprint.features[0]?.geometry
    if (geometry?.type !== 'Polygon') return
    const ring = geometry.coordinates[0]
    const paths = ring.slice(0, -1).map(([lng, lat]) => ({ lat, lng }))
    footprintOverlay.current?.setMap(null)
    footprintOverlay.current = new google.maps.Polygon({
      map: map.current,
      paths,
      fillColor: '#ff5a36',
      fillOpacity: 0.3,
      strokeColor: '#ff6a35',
      strokeOpacity: 1,
      strokeWeight: 3,
      clickable: false,
    })
    const site = sites.find((item) => item.id === selectedId)
    if (site) {
      map.current.panTo({ lat: site.latitude, lng: site.longitude })
      map.current.setZoom(15)
    }
  }, [footprint, ready, selectedId, sites])

  if (!runtimeGoogleMapsApiKey || error) {
    return <div className="map-fallback">
      <div className="map-grid" />
      {sites.map((site, index) => <button
        key={site.id}
        className={`fallback-pin fallback-pin--${index + 1} ${selectedId === site.id ? 'active' : ''}`}
        onClick={() => onSelect(site.id)}
      ><MapPin size={15} /> {site.metro}</button>)}
      <p>{error || 'Add GOOGLE_MAPS_API_KEY to render the live thermal map.'}</p>
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
