import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Circle, Database, Droplets, Flame, Hexagon, Layers3, Leaf, LocateFixed, MapIcon, PawPrint, RotateCcw, Search, ThermometerSun, Waves, X } from 'lucide-react'
import { artifactUrl } from '../../api/client'
import { getVegetationSample } from '../../api/runs'
import { loadGoogleMaps } from '../../api/googleMaps'
import { runtimeGoogleMapsApiKey } from '../../api/runtimeConfig'
import type { RunRecord, StudyArea, VegetationSample } from '../../types/run'
import { parseMapCoordinates } from './coordinates'

const MAX_AREA_SQ_MI = 150
const SQ_METERS_PER_SQ_MILE = 2_589_988.110336
const METERS_PER_MILE = 1609.344
const MAX_CIRCLE_RADIUS_METERS = Math.sqrt((MAX_AREA_SQ_MI * SQ_METERS_PER_SQ_MILE) / Math.PI)

type DrawMode = 'circle' | 'polygon' | null
type MapMode = 'climate' | 'vegetation' | 'species' | 'wildfire' | 'wetlands'

const MAP_MODES: Array<{ id: MapMode; label: string; artifact?: string; icon: React.ReactNode }> = [
  { id: 'climate', label: 'Climate', icon: <MapIcon size={14} /> },
  { id: 'vegetation', label: 'Vegetation', icon: <Leaf size={14} /> },
  { id: 'species', label: 'Species', artifact: 'species biodiversity', icon: <PawPrint size={14} /> },
  { id: 'wildfire', label: 'Wildfire', artifact: 'wildfire layer', icon: <Flame size={14} /> },
  { id: 'wetlands', label: 'Wetlands', artifact: 'wetlands layer', icon: <Waves size={14} /> },
]

function polygonCoordinates(path: google.maps.MVCArray<google.maps.LatLng>) {
  const ring = path.getArray().map((point) => [point.lng(), point.lat()] as [number, number])
  if (ring.length) ring.push([...ring[0]] as [number, number])
  return ring
}

function circleCoordinates(center: google.maps.LatLng, radius: number) {
  const ring: [number, number][] = []
  for (let heading = 0; heading < 360; heading += 6) {
    const point = google.maps.geometry.spherical.computeOffset(center, radius, heading)
    ring.push([point.lng(), point.lat()])
  }
  ring.push([...ring[0]] as [number, number])
  return ring
}

function boundsFor(ring: [number, number][]): [number, number, number, number] {
  const lng = ring.map(([value]) => value)
  const lat = ring.map(([, value]) => value)
  return [Math.min(...lng), Math.min(...lat), Math.max(...lng), Math.max(...lat)]
}

function centerFor(ring: [number, number][]): [number, number] {
  const points = ring.slice(0, -1)
  return [points.reduce((sum, point) => sum + point[0], 0) / points.length, points.reduce((sum, point) => sum + point[1], 0) / points.length]
}

function MetricCard({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: string; detail: string }) {
  return <div className="map-metric"><div className="map-metric__icon">{icon}</div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

export function ResearchMap({ run, studyArea, onStudyAreaChange, controlsHost }: { run?: RunRecord; studyArea?: StudyArea; onStudyAreaChange: (area?: StudyArea) => void; controlsHost: HTMLElement | null }) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<google.maps.Map | null>(null)
  const overlay = useRef<google.maps.Circle | google.maps.Polygon | null>(null)
  const analysisLayer = useRef<google.maps.Data | null>(null)
  const vegetationOverlay = useRef<google.maps.GroundOverlay | null>(null)
  const polygonDraft = useRef<google.maps.LatLngLiteral[]>([])
  const modeRef = useRef<DrawMode>(null)
  const callbackRef = useRef(onStudyAreaChange)
  const [mode, setMode] = useState<DrawMode>(null)
  const [draftCount, setDraftCount] = useState(0)
  const [search, setSearch] = useState('')
  const [coordinateLatitude, setCoordinateLatitude] = useState('')
  const [coordinateLongitude, setCoordinateLongitude] = useState('')
  const [coordinateStatus, setCoordinateStatus] = useState('')
  const [area, setArea] = useState(studyArea?.area_sq_mi || 0)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const [renderingType, setRenderingType] = useState('Loading')
  const [mapMode, setMapMode] = useState<MapMode>('climate')
  const [layerMessage, setLayerMessage] = useState('')
  const [vegetationMetric, setVegetationMetric] = useState<'ndvi' | 'ndmi' | 'stress'>('stress')
  const [vegetationPeriod, setVegetationPeriod] = useState<'current' | 'baseline'>('current')
  const [vegetationOpacity, setVegetationOpacity] = useState(72)
  const [vegetationSample, setVegetationSample] = useState<VegetationSample>()
  const [sampleLoading, setSampleLoading] = useState(false)
  const apiKey = runtimeGoogleMapsApiKey || import.meta.env.VITE_GOOGLE_MAPS_API_KEY || ''

  useEffect(() => {
    callbackRef.current = onStudyAreaChange
  }, [onStudyAreaChange])

  const chooseMode = (next: DrawMode) => {
    modeRef.current = next
    setMode(next)
    setError('')
    if (next !== 'polygon') polygonDraft.current = []
    setDraftCount(next === 'polygon' ? polygonDraft.current.length : 0)
    map.current?.setOptions({ draggableCursor: next ? 'crosshair' : undefined })
  }

  const clearShape = (notify = true) => {
    overlay.current?.setMap(null)
    overlay.current = null
    polygonDraft.current = []
    setDraftCount(0)
    setArea(0)
    setError('')
    chooseMode(null)
    if (notify) callbackRef.current(undefined)
  }

  const emitCircle = (shape: google.maps.Circle) => {
    const center = shape.getCenter()
    if (!center) return
    const radius = Math.min(shape.getRadius(), MAX_CIRCLE_RADIUS_METERS)
    if (shape.getRadius() !== radius) shape.setRadius(radius)
    const ring = circleCoordinates(center, radius)
    const areaSqMi = Math.PI * radius * radius / SQ_METERS_PER_SQ_MILE
    setArea(areaSqMi)
    setError('')
    callbackRef.current({ shape: 'circle', geometry: { type: 'Polygon', coordinates: [ring] }, center: [center.lng(), center.lat()], bbox: boundsFor(ring), area_sq_mi: areaSqMi, radius_miles: radius / METERS_PER_MILE, label: 'User-drawn habitat area' })
  }

  const emitPolygon = (shape: google.maps.Polygon) => {
    const ring = polygonCoordinates(shape.getPath())
    if (ring.length < 4) return
    const areaSqMi = google.maps.geometry.spherical.computeArea(shape.getPath()) / SQ_METERS_PER_SQ_MILE
    setArea(areaSqMi)
    setError(areaSqMi > MAX_AREA_SQ_MI ? `Area exceeds the ${MAX_AREA_SQ_MI} mi² limit. Move the handles inward.` : '')
    callbackRef.current({ shape: 'polygon', geometry: { type: 'Polygon', coordinates: [ring] }, center: centerFor(ring), bbox: boundsFor(ring), area_sq_mi: areaSqMi, label: 'User-drawn habitat area' })
  }

  const attachPolygonEditing = (shape: google.maps.Polygon) => {
    const update = () => emitPolygon(shape)
    shape.getPath().addListener('set_at', update)
    shape.getPath().addListener('insert_at', update)
    shape.getPath().addListener('remove_at', update)
    shape.addListener('dragend', update)
  }

  const finishPolygon = () => {
    const shape = overlay.current
    if (!(shape instanceof google.maps.Polygon) || polygonDraft.current.length < 3) return
    shape.setEditable(true)
    shape.setDraggable(true)
    attachPolygonEditing(shape)
    emitPolygon(shape)
    chooseMode(null)
  }

  useEffect(() => {
    if (!container.current || !apiKey) return
    let active = true
    loadGoogleMaps(apiKey).then(() => {
      if (!active || !container.current) return
      const initialCenter = studyArea ? { lng: studyArea.center[0], lat: studyArea.center[1] } : { lat: 39.5, lng: -98.35 }
      map.current = new google.maps.Map(container.current, {
        center: initialCenter,
        zoom: studyArea ? 9 : 4,
        mapTypeId: google.maps.MapTypeId.ROADMAP,
        renderingType: google.maps.RenderingType.VECTOR,
        isFractionalZoomEnabled: true,
        gestureHandling: 'greedy',
        streetViewControl: false,
        mapTypeControl: true,
        mapTypeControlOptions: { mapTypeIds: [google.maps.MapTypeId.ROADMAP, google.maps.MapTypeId.SATELLITE] },
        fullscreenControl: false,
        clickableIcons: false,
      })
      google.maps.event.addListenerOnce(map.current, 'idle', () => {
        setRenderingType(map.current?.getRenderingType() === google.maps.RenderingType.VECTOR ? 'Vector' : 'Compatibility')
      })
      if (studyArea) {
        if (studyArea.shape === 'circle' && studyArea.radius_miles) {
          const circle = new google.maps.Circle({ map: map.current, center: initialCenter, radius: studyArea.radius_miles * METERS_PER_MILE, editable: !run, draggable: !run, strokeColor: '#df5b43', strokeWeight: 3, fillColor: '#e9ad75', fillOpacity: .26 })
          overlay.current = circle
          if (!run) { circle.addListener('radius_changed', () => emitCircle(circle)); circle.addListener('center_changed', () => emitCircle(circle)) }
        } else {
          const path = studyArea.geometry.coordinates[0].slice(0, -1).map(([lng, lat]) => ({ lng, lat }))
          const polygon = new google.maps.Polygon({ map: map.current, paths: path, editable: !run, draggable: !run, geodesic: true, strokeColor: '#df5b43', strokeWeight: 3, fillColor: '#e9ad75', fillOpacity: .26 })
          overlay.current = polygon
          if (!run) attachPolygonEditing(polygon)
        }
        const bounds = new google.maps.LatLngBounds({ south: studyArea.bbox[1], west: studyArea.bbox[0], north: studyArea.bbox[3], east: studyArea.bbox[2] })
        map.current.fitBounds(bounds, 70)
      }
      map.current.addListener('click', (event: google.maps.MapMouseEvent) => {
        if (!event.latLng || !modeRef.current || run) return
        if (modeRef.current === 'circle') {
          clearShape(false)
          const circle = new google.maps.Circle({ map: map.current, center: event.latLng, radius: 5 * METERS_PER_MILE, editable: true, draggable: true, strokeColor: '#df5b43', strokeWeight: 3, fillColor: '#e9ad75', fillOpacity: .26 })
          overlay.current = circle
          circle.addListener('radius_changed', () => emitCircle(circle))
          circle.addListener('center_changed', () => emitCircle(circle))
          emitCircle(circle)
          chooseMode(null)
        } else {
          polygonDraft.current.push(event.latLng.toJSON())
          setDraftCount(polygonDraft.current.length)
          if (!(overlay.current instanceof google.maps.Polygon)) {
            overlay.current?.setMap(null)
            overlay.current = new google.maps.Polygon({ map: map.current, paths: polygonDraft.current, geodesic: true, strokeColor: '#df5b43', strokeWeight: 3, fillColor: '#e9ad75', fillOpacity: .26 })
          } else overlay.current.setPath(polygonDraft.current)
        }
      })
      setReady(true)
    }).catch((reason: Error) => active && setError(reason.message))
    return () => { active = false; overlay.current?.setMap(null); vegetationOverlay.current?.setMap(null); map.current = null }
  // The map intentionally initializes once; App remounts it when a persisted run is opened.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    analysisLayer.current?.setMap(null)
    analysisLayer.current = null
    vegetationOverlay.current?.setMap(null)
    vegetationOverlay.current = null
    if (!ready || !map.current || mapMode === 'climate') return
    let active = true
    if (mapMode === 'vegetation') {
      const period = vegetationMetric === 'stress' ? 'anomaly' : vegetationPeriod
      const layer = run?.vegetation?.layers.find((item) => item.metric === vegetationMetric && item.period === period)
      if (!layer?.download_url) {
        const message = run?.status === 'COMPLETED'
          ? run.vegetation?.warnings[0] || 'No usable Sentinel-2 vegetation layer was returned.'
          : 'The Sentinel-2 vegetation layer is building with the research run.'
        Promise.resolve().then(() => active && setLayerMessage(message))
        return () => { active = false }
      }
      const [west, south, east, north] = layer.bounds
      const ground = new google.maps.GroundOverlay(
        artifactUrl(layer.download_url)!,
        { west, south, east, north },
        { map: map.current, opacity: vegetationOpacity / 100 },
      )
      vegetationOverlay.current = ground
      Promise.resolve().then(() => active && setLayerMessage(`${layer.label} · ${layer.resolution_m.toFixed(0)} m · ${run?.vegetation?.valid_coverage_pct.toFixed(0)}% usable`))
      return () => {
        active = false
        ground.setMap(null)
        if (vegetationOverlay.current === ground) vegetationOverlay.current = null
      }
    }
    const mode = MAP_MODES.find((item) => item.id === mapMode)
    const artifact = run?.artifacts.find((item) => item.name.toLowerCase().includes(mode?.artifact || ''))
    if (!artifact?.download_url) {
      const message = run?.status === 'COMPLETED' ? 'No mapped evidence was returned for this area.' : 'This evidence layer is building with the research run.'
      Promise.resolve().then(() => active && setLayerMessage(message))
      return () => { active = false }
    }
    fetch(artifactUrl(artifact.download_url)!).then((response) => {
      if (!response.ok) throw new Error('Layer download failed')
      return response.json() as Promise<GeoJSON.FeatureCollection>
    }).then((geojson) => {
      if (!active || !map.current) return
      const layer = new google.maps.Data({ map: map.current })
      const features = layer.addGeoJson(geojson)
      layer.setStyle(() => {
        if (mapMode === 'species') return { icon: { path: google.maps.SymbolPath.CIRCLE, scale: 4.5, fillColor: '#136b4f', fillOpacity: .82, strokeColor: '#ffffff', strokeWeight: 1 } }
        if (mapMode === 'wildfire') return { icon: { path: google.maps.SymbolPath.CIRCLE, scale: 6, fillColor: '#d94f32', fillOpacity: .9, strokeColor: '#fff1e8', strokeWeight: 1.5 } }
        return { fillColor: '#4a91a8', fillOpacity: .38, strokeColor: '#216c86', strokeWeight: 1.5 }
      })
      analysisLayer.current = layer
      setLayerMessage(features.length ? `${features.length.toLocaleString()} mapped evidence features` : 'No mapped evidence was returned for this area.')
    }).catch(() => active && setLayerMessage('The evidence layer could not be displayed.'))
    return () => {
      active = false
      analysisLayer.current?.setMap(null)
      analysisLayer.current = null
    }
  }, [mapMode, ready, run?.artifacts, run?.status, run?.vegetation, vegetationMetric, vegetationPeriod, vegetationOpacity])

  useEffect(() => {
    if (!ready || !map.current || mapMode !== 'vegetation' || !run?.vegetation?.sample_grid_artifact_id) return
    const listener = map.current.addListener('click', async (event: google.maps.MapMouseEvent) => {
      if (!event.latLng) return
      setSampleLoading(true)
      setVegetationSample(undefined)
      try {
        setVegetationSample(await getVegetationSample(run.id, event.latLng.lat(), event.latLng.lng()))
      } catch {
        setVegetationSample({ latitude: event.latLng.lat(), longitude: event.latLng.lng(), classification: 'No valid observation' })
      } finally {
        setSampleLoading(false)
      }
    })
    return () => listener.remove()
  }, [mapMode, ready, run?.id, run?.vegetation?.sample_grid_artifact_id])

  const submitSearch = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!map.current || !search.trim()) return
    const results = await new google.maps.Geocoder().geocode({ address: search.trim() })
    const result = results.results[0]
    if (!result) { setError('Google Maps could not find that location.'); return }
    map.current.fitBounds(result.geometry.viewport)
    setCoordinateStatus('')
    setError('')
  }

  const submitCoordinates = (event: React.FormEvent) => {
    event.preventDefault()
    if (!map.current) return
    const result = parseMapCoordinates(coordinateLatitude, coordinateLongitude)
    if (!result.coordinate) {
      setCoordinateStatus('')
      setError(result.error || 'Coordinates are invalid.')
      return
    }
    map.current.panTo(result.coordinate)
    map.current.setZoom(11)
    setError('')
    setCoordinateStatus(
      `Map centered at ${result.coordinate.lat.toFixed(4)}, ${result.coordinate.lng.toFixed(4)}`,
    )
  }

  const metrics = run?.metrics || {}
  const sourceTarget = run ? (run.research_spec?.habitat_type === 'custom_habitat' ? 6 : 3) : 6
  const formatMetric = (key: string, suffix: string) => typeof metrics[key] === 'number' ? `${(metrics[key] as number) >= 0 ? '+' : ''}${(metrics[key] as number).toFixed(2)} ${suffix}` : 'Awaiting analysis'
  const drawingControls = <section className="area-drawing-panel" aria-label="Study area drawing controls">
    <form onSubmit={submitSearch}><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="City, habitat, or address" disabled={!ready || Boolean(run)} /></form>
    <form className="coordinate-search" onSubmit={submitCoordinates} aria-label="Go to map coordinates"><LocateFixed size={15} /><input aria-label="Latitude" inputMode="decimal" value={coordinateLatitude} onChange={(event) => setCoordinateLatitude(event.target.value)} placeholder="Latitude" disabled={!ready || Boolean(run)} /><input aria-label="Longitude" inputMode="decimal" value={coordinateLongitude} onChange={(event) => setCoordinateLongitude(event.target.value)} placeholder="Longitude" disabled={!ready || Boolean(run)} /><button type="submit" disabled={!ready || Boolean(run)}>Go</button></form>
    {coordinateStatus && <p className="coordinate-status" role="status">{coordinateStatus}</p>}
    <div className="draw-buttons"><button className={mode === 'circle' ? 'active' : ''} onClick={() => chooseMode('circle')} disabled={!ready || Boolean(run)}><Circle size={15} /> Circle</button><button className={mode === 'polygon' ? 'active' : ''} onClick={() => chooseMode('polygon')} disabled={!ready || Boolean(run)}><Hexagon size={15} /> Polygon</button><button onClick={() => clearShape()} disabled={!ready || Boolean(run)} aria-label="Clear study area"><RotateCcw size={15} /></button></div>
    {mode === 'circle' && <p>Click the center, then resize or drag the circle.</p>}
    {mode === 'polygon' && <p>Click at least three map points. <button className="finish-shape" onClick={finishPolygon} disabled={draftCount < 3}>Finish polygon</button></p>}
    <div className={`area-measure ${area > MAX_AREA_SQ_MI ? 'area-measure--invalid' : ''}`}><span>Selected area</span><strong>{area ? `${area.toFixed(1)} mi²` : 'Not drawn'}</strong><small>Maximum {MAX_AREA_SQ_MI} mi²</small></div>
    {error && <div className="area-error">{error}</div>}
  </section>

  return <div className="map-wrap" aria-label="Google map for drawing a habitat study area">
    <div ref={container} className="google-map-canvas" />
    {!apiKey && <div className="map-key-message"><strong>Google Maps key required</strong><span>Add a browser-restricted GOOGLE_MAPS_API_KEY to the root .env file.</span></div>}
    {controlsHost && createPortal(drawingControls, controlsHost)}
    <section className="map-mode-panel" aria-label="Ecological map modes">
      <div className="map-mode-buttons">{MAP_MODES.map((item) => <button key={item.id} className={mapMode === item.id ? 'active' : ''} onClick={() => { setMapMode(item.id); setLayerMessage(item.id === 'climate' ? '' : 'Loading mapped evidence…') }} disabled={item.id !== 'climate' && !run}>{item.icon}<span>{item.label}</span></button>)}</div>
      {layerMessage && <p>{layerMessage}</p>}
    </section>
    {mapMode === 'vegetation' && <section className="vegetation-controls" aria-label="Vegetation layer controls">
      <header><div><span className="eyebrow">Sentinel-2 intelligence</span><strong>Vegetation condition</strong></div><span className={`vegetation-quality vegetation-quality--${run?.vegetation?.status || 'pending'}`}>{run?.vegetation?.status || 'Building'}</span></header>
      <div className="vegetation-layer-buttons" role="group" aria-label="Vegetation metric">
        <button className={vegetationMetric === 'ndvi' ? 'active' : ''} onClick={() => setVegetationMetric('ndvi')}>Greenness</button>
        <button className={vegetationMetric === 'ndmi' ? 'active' : ''} onClick={() => setVegetationMetric('ndmi')}>Moisture</button>
        <button className={vegetationMetric === 'stress' ? 'active' : ''} onClick={() => setVegetationMetric('stress')}>Stress</button>
      </div>
      {vegetationMetric !== 'stress' && <div className="vegetation-period-buttons" role="group" aria-label="Vegetation comparison period"><button className={vegetationPeriod === 'current' ? 'active' : ''} onClick={() => setVegetationPeriod('current')}>Current</button><button className={vegetationPeriod === 'baseline' ? 'active' : ''} onClick={() => setVegetationPeriod('baseline')}>5-year baseline</button></div>}
      <label className="vegetation-opacity"><span>Overlay opacity</span><input aria-label="Vegetation overlay opacity" type="range" min="20" max="100" value={vegetationOpacity} onChange={(event) => setVegetationOpacity(Number(event.target.value))} /><strong>{vegetationOpacity}%</strong></label>
      {run?.vegetation?.layers.find((item) => item.metric === vegetationMetric && item.period === (vegetationMetric === 'stress' ? 'anomaly' : vegetationPeriod))?.legend && <div className="vegetation-legend">{run.vegetation.layers.find((item) => item.metric === vegetationMetric && item.period === (vegetationMetric === 'stress' ? 'anomaly' : vegetationPeriod))!.legend.map((stop) => <span key={`${stop.value}-${stop.label}`}><i style={{ background: stop.color }} />{stop.label}</span>)}</div>}
      {run?.vegetation && <div className="vegetation-provenance"><span>{run.vegetation.latest_observation_date ? `Observed ${new Date(`${run.vegetation.latest_observation_date}T00:00:00`).toLocaleDateString()}` : 'Observation date pending'}</span><span>{run.vegetation.resolution_m.toFixed(0)} m · {run.vegetation.valid_coverage_pct.toFixed(0)}% cloud-free</span><span>{run.vegetation.attribution}</span></div>}
      <small>Click the mapped study area for exact current and baseline values.</small>
    </section>}
    {mapMode === 'vegetation' && (sampleLoading || vegetationSample) && <section className="vegetation-sample" aria-live="polite">
      {sampleLoading ? <span>Reading satellite grid…</span> : vegetationSample && <><button aria-label="Close vegetation sample" onClick={() => setVegetationSample(undefined)}><X size={14} /></button><span className="eyebrow">Selected pixel</span><strong>{vegetationSample.classification}</strong><dl><div><dt>NDVI</dt><dd>{vegetationSample.current_ndvi?.toFixed(3) ?? '—'} <small>baseline {vegetationSample.baseline_ndvi?.toFixed(3) ?? '—'}</small></dd></div><div><dt>NDMI</dt><dd>{vegetationSample.current_ndmi?.toFixed(3) ?? '—'} <small>baseline {vegetationSample.baseline_ndmi?.toFixed(3) ?? '—'}</small></dd></div><div><dt>Seasonal percentile</dt><dd>{vegetationSample.seasonal_percentile?.toFixed(0) ?? '—'}%</dd></div></dl></>}
    </section>}
    <div className="map-metrics-panel" aria-label="Research metrics">
      {mapMode === 'vegetation' ? <>
        <MetricCard icon={<Leaf size={16} />} label="Current NDVI" value={typeof run?.vegetation?.median_ndvi === 'number' ? run.vegetation.median_ndvi.toFixed(3) : 'Awaiting analysis'} detail="Sentinel-2 greenness" />
        <MetricCard icon={<Droplets size={16} />} label="Current NDMI" value={typeof run?.vegetation?.median_ndmi === 'number' ? run.vegetation.median_ndmi.toFixed(3) : 'Awaiting analysis'} detail="Canopy moisture" />
        <MetricCard icon={<Layers3 size={16} />} label="Stressed area" value={typeof run?.vegetation?.stressed_area_pct === 'number' ? `${run.vegetation.stressed_area_pct.toFixed(1)}%` : 'Insufficient evidence'} detail={`${run?.vegetation?.stressed_area_sq_mi?.toFixed(1) || '—'} mi²`} />
        <MetricCard icon={<Database size={16} />} label="Confidence" value={typeof run?.vegetation?.confidence === 'number' ? `${(run.vegetation.confidence * 100).toFixed(0)}%` : 'Awaiting analysis'} detail={`${run?.vegetation?.valid_coverage_pct?.toFixed(0) || 0}% usable coverage`} />
      </> : <>
      <MetricCard icon={<ThermometerSun size={16} />} label="Temperature trend" value={formatMetric('regional_temperature_trend_c_per_decade', '°C/dec')} detail="NASA regional evidence" />
      <MetricCard icon={<Droplets size={16} />} label="Precipitation trend" value={formatMetric('regional_precipitation_trend_mm_per_decade', 'mm/dec')} detail="Habitat climate pressure" />
      <MetricCard icon={<Database size={16} />} label="Evidence sources" value={`${run?.selected_datasets.length || 0} / ${sourceTarget}`} detail={run ? 'Climate and ecological roles selected' : 'Draw an area and start research'} />
      </>}
    </div>
    <div className="layer-chip"><Layers3 size={15} /> Google Maps · {renderingType} <b>{studyArea ? 1 : 0}</b></div>
  </div>
}
