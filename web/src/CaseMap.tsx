import { useEffect, useRef } from 'react'
import { LngLatBounds, Map as MLMap, NavigationControl, setWorkerUrl, type GeoJSONSource, type MapMouseEvent } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

// Production builds do not follow MapLibre's own relative worker URL, so hand it the bundled worker.
setWorkerUrl(workerUrl)
import type { CaseView, GeoJSON, Recommendation } from './api'

const STYLE = 'https://tiles.openfreemap.org/styles/positron'
type FC = { type: 'FeatureCollection'; features: any[] }
const empty = (): FC => ({ type: 'FeatureCollection', features: [] })

interface Props {
  reach: GeoJSON | null
  view?: CaseView | null
  target?: Recommendation | null
  picked?: { lat: number; lon: number } | null
  onPick?: (lat: number, lon: number) => void
  height?: number | string
  label?: string
  stretches?: [number, number][][]
  /** Citizen maps show the stream and nearby places, never the suspected outfalls. */
  citizen?: boolean
}

function layersData(reach: GeoJSON, view: CaseView | null | undefined, target: Recommendation | null | undefined, citizen = false) {
  const pNode = new Map<string, number>((view?.ribbon ?? []).map((r) => [r.node_id, r.p_polluted]))
  const nodes = new Map<string, [number, number]>()
  for (const f of reach.features) if (f.properties.role === 'node') nodes.set(f.properties.id, f.geometry.coordinates)
  const edges: FC = { type: 'FeatureCollection', features: reach.features.filter((f) => f.properties.role === 'edge').map((f) => ({
    ...f, properties: { ...f.properties, p: pNode.get(f.properties.from) ?? 0 } })) }
  const cands: FC = { type: 'FeatureCollection', features: (view?.sources ?? reach.features.filter((f) => f.properties.role === 'candidate').map((f) => ({
    id: f.properties.id, label: f.properties.label, p: 0, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] }))).map((s: any) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
    properties: { id: s.id, p: s.p, text: view ? `${s.label} ${Math.round(s.p * 100)}%` : s.label } })) }
  if (citizen) cands.features = []
  const places: FC = { type: 'FeatureCollection', features: reach.features.filter((f) => f.properties.role === 'place') }
  const obs: FC = { type: 'FeatureCollection', features: (view?.observations ?? []).map((o) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [o.lon, o.lat] },
    properties: { cls: o.kind === 'report' ? 'report' : o.positive ? 'positive' : 'clean' } })) }
  let tgt = empty()
  if (target) {
    const c = target.check
    const coord = c.candidate_id
      ? cands.features.find((f) => f.properties.id === c.candidate_id)?.geometry.coordinates
      : c.node_id ? nodes.get(c.node_id) : undefined
    if (coord) tgt = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: coord }, properties: {} }] }
  }
  return { edges, cands, places, obs, tgt }
}

export default function CaseMap({ reach, view, target, picked, onPick, height = '100%', label, stretches, citizen = false }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const ready = useRef(false)
  const pending = useRef<(() => void) | null>(null)
  const pickRef = useRef(onPick)
  pickRef.current = onPick

  useEffect(() => {
    if (!el.current || map.current) return
    const m = new MLMap({ container: el.current, style: STYLE, center: [-8.41, 40.22], zoom: 13, attributionControl: { compact: true } })
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    m.on('load', () => {
      for (const id of ['edges', 'cands', 'places', 'obs', 'tgt', 'pick', 'stretch']) m.addSource(id, { type: 'geojson', data: empty() })
      m.addLayer({ id: 'edges-casing', type: 'line', source: 'edges', paint: { 'line-color': '#ffffff', 'line-width': 9, 'line-opacity': 0.9 }, layout: { 'line-cap': 'round', 'line-join': 'round' } })
      m.addLayer({ id: 'edges', type: 'line', source: 'edges', filter: ['!=', ['get', 'culvert'], true],
        paint: { 'line-width': 6, 'line-color': ['interpolate', ['linear'], ['get', 'p'], 0, '#6F9EA3', 0.25, '#E3B04B', 0.6, '#D9731F', 0.9, '#B3261E'] },
        layout: { 'line-cap': 'round', 'line-join': 'round' } })
      m.addLayer({ id: 'edges-culvert', type: 'line', source: 'edges', filter: ['==', ['get', 'culvert'], true],
        paint: { 'line-width': 4, 'line-dasharray': [1, 1.2], 'line-color': ['interpolate', ['linear'], ['get', 'p'], 0, '#6F9EA3', 0.25, '#E3B04B', 0.6, '#D9731F', 0.9, '#B3261E'] } })
      m.addLayer({ id: 'stretch', type: 'line', source: 'stretch', paint: { 'line-color': '#B3261E', 'line-width': 9, 'line-opacity': 0.55 },
        layout: { 'line-cap': 'round', 'line-join': 'round' } })
      m.addLayer({ id: 'places', type: 'circle', source: 'places', paint: { 'circle-radius': 6, 'circle-color': '#6B5CA5', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } })
      m.addLayer({ id: 'places-label', type: 'symbol', source: 'places', layout: { 'text-field': ['get', 'label'], 'text-size': 11, 'text-offset': [0, 1.3], 'text-font': ['Noto Sans Regular'] },
        paint: { 'text-color': '#4B3F80', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } })
      m.addLayer({ id: 'tgt', type: 'circle', source: 'tgt', paint: { 'circle-radius': 20, 'circle-color': 'rgba(14,107,107,0.12)', 'circle-stroke-color': '#0E6B6B', 'circle-stroke-width': 2.5 } })
      m.addLayer({ id: 'cands', type: 'circle', source: 'cands', paint: {
        'circle-radius': ['+', 4, ['*', 16, ['sqrt', ['get', 'p']]]],
        'circle-color': ['interpolate', ['linear'], ['get', 'p'], 0, '#FFFFFF', 0.3, '#E3B04B', 0.85, '#B3261E'],
        'circle-stroke-color': '#14242A', 'circle-stroke-width': 1.5 } })
      m.addLayer({ id: 'cands-label', type: 'symbol', source: 'cands', layout: { 'text-field': ['get', 'text'], 'text-size': 11, 'text-offset': [0, -1.6], 'text-font': ['Noto Sans Bold'], 'text-allow-overlap': false },
        paint: { 'text-color': '#14242A', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } })
      m.addLayer({ id: 'obs', type: 'circle', source: 'obs', paint: { 'circle-radius': 5.5, 'circle-stroke-color': '#fff', 'circle-stroke-width': 2,
        'circle-color': ['match', ['get', 'cls'], 'report', '#9A5A06', 'positive', '#B3261E', '#4F7A22'] } })
      m.addLayer({ id: 'pick', type: 'circle', source: 'pick', paint: { 'circle-radius': 8, 'circle-color': '#0E6B6B', 'circle-stroke-color': '#fff', 'circle-stroke-width': 3 } })
      // Start with the attribution collapsed to its (i) button so it does not cover small maps.
      el.current?.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show')
      ready.current = true
      pending.current?.()
      pending.current = null
    })
    m.on('click', (e: MapMouseEvent) => pickRef.current?.(e.lngLat.lat, e.lngLat.lng))
    map.current = m
    // MapLibre only follows window resizes. Maps inside cards change size as the layout settles (fonts, the
    // lazy-loaded map chunk, a mission appearing), so resize with the container or part of the canvas stays blank.
    const ro = new ResizeObserver(() => m.resize())
    ro.observe(el.current)
    return () => { ro.disconnect(); m.remove(); map.current = null; ready.current = false }
  }, [])

  // A citizen mission map centres on the spot to visit; every other map fits the whole reach.
  const focus = citizen && !onPick && picked ? [picked.lat, picked.lon] as const : null

  // Fit to the reach once it is known.
  useEffect(() => {
    const m = map.current
    if (!m) return
    const pts0 = stretches?.flat() ?? []
    if (!reach && pts0.length) {
      const b = pts0.reduce((acc, p) => acc.extend(p), new LngLatBounds(pts0[0], pts0[0]))
      m.fitBounds(b, { padding: 50, duration: 0 })
      return
    }
    if (!reach) return
    if (focus) { m.jumpTo({ center: [focus[1], focus[0]], zoom: 14.5 }); return }  // a mission: show where to go
    const pts = reach.features.filter((f) => f.properties.role === 'node').map((f) => f.geometry.coordinates as [number, number])
    if (!pts.length) return
    const b = pts.reduce((acc, p) => acc.extend(p), new LngLatBounds(pts[0], pts[0]))
    m.fitBounds(b, { padding: 50, duration: 0 })
  }, [reach, stretches, focus?.[0], focus?.[1]])

  useEffect(() => {
    const m = map.current
    if (!m) return
    const apply = () => {
      ;(m.getSource('stretch') as GeoJSONSource).setData({ type: 'FeatureCollection', features: (stretches ?? []).map((c) => (
        { type: 'Feature', geometry: { type: 'LineString', coordinates: c }, properties: {} })) } as any)
      if (!reach) return
      const d = layersData(reach, view, target, citizen)
      ;(m.getSource('edges') as GeoJSONSource).setData(d.edges as any)
      ;(m.getSource('cands') as GeoJSONSource).setData(d.cands as any)
      ;(m.getSource('places') as GeoJSONSource).setData(d.places as any)
      ;(m.getSource('obs') as GeoJSONSource).setData(d.obs as any)
      ;(m.getSource('tgt') as GeoJSONSource).setData(d.tgt as any)
      ;(m.getSource('pick') as GeoJSONSource).setData((picked
        ? { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [picked.lon, picked.lat] }, properties: {} }] }
        : empty()) as any)
    }
    if (ready.current) apply()
    else pending.current = apply
  }, [reach, view, target, picked, stretches, citizen])

  return <div ref={el} className="map" style={{ height }} role="region" aria-label={label ?? 'Map of the stream'} />
}
