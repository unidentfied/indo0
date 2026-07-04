import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import DeckGL from '@deck.gl/react'
import type { DeckGLRef } from '@deck.gl/react'
import { ScatterplotLayer, LineLayer, PolygonLayer } from '@deck.gl/layers'
import { HeatmapLayer } from '@deck.gl/aggregation-layers'
import type { PickingInfo } from '@deck.gl/core'
import { Map } from 'react-map-gl/maplibre'
import type { MapRef } from 'react-map-gl/maplibre'
import { ZoomIn, ZoomOut, Home } from 'lucide-react'
import MapLegend from './MapLegend'
import StressDrawer from './StressDrawer'
import { api } from '../services/api'
import type { AssetDetail, GridCellFeature, WaterMainLine } from '../types'
import 'maplibre-gl/dist/maplibre-gl.css'

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const NAIROBI_CENTER = { lat: -1.2833, lng: 36.8219 }
const DEFAULT_ZOOM = 13

type LayerId = 'heatmap' | 'scatterplot' | 'waterMains' | 'grid'

interface LayerState {
  id: LayerId
  label: string
  color: string
  visible: boolean
}

const defaultLayers: LayerState[] = [
  { id: 'heatmap', label: 'Stress Heatmap', color: '#ef4444', visible: true },
  { id: 'scatterplot', label: 'Stress Points', color: '#eab308', visible: true },
  { id: 'waterMains', label: 'Water Mains', color: '#3b82f6', visible: true },
  { id: 'grid', label: 'Stress Grid', color: '#a855f7', visible: false },
]

function stressToColor(stress: number): [number, number, number] {
  if (stress >= 80) return [239, 68, 68]
  if (stress >= 60) return [245, 158, 11]
  if (stress >= 40) return [234, 179, 8]
  if (stress >= 20) return [132, 204, 22]
  return [34, 197, 94]
}

function stressToColorArray(stress: number): [number, number, number, number] {
  return [...stressToColor(stress), 180] as [number, number, number, number]
}

interface StressPoint {
  lng: number
  lat: number
  stress: number
  asset_id: string
  classification: string
  recurring: boolean
}

function generateWaterMains(): WaterMainLine[] {
  return [
    { id: 'WM-001', coordinates: [[36.8090, -1.2670], [36.8122, -1.2760], [36.8150, -1.2900], [36.8120, -1.2980]], stress: 72, name: 'Westlands\u2013Upper Hill Trunk' },
    { id: 'WM-002', coordinates: [[36.8219, -1.2833], [36.8150, -1.2900], [36.8120, -1.2900]], stress: 45, name: 'CBD\u2013Upper Hill Connector' },
    { id: 'WM-003', coordinates: [[36.7850, -1.2900], [36.7900, -1.3000], [36.8000, -1.3050], [36.8122, -1.2975]], stress: 88, name: 'Kilimani\u2013Upper Hill Main' },
  ]
}

function generateAssetDetail(assetId: string, lat: number, lng: number, stress: number): AssetDetail {
  const now = new Date()
  const timeseries = Array.from({ length: 24 }, (_, i) => {
    const hour = new Date(now.getTime() - (23 - i) * 3600_000)
    return { time: hour.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), stress: Math.round(Math.max(10, stress + (Math.random() - 0.5) * 40)) }
  })
  const types = ['power', 'water', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports'] as const
  const names = ['Substation 4-A', 'Pump Station W-102', 'A8 Junction Westlands', 'Transformer 7-B', 'Reservoir Upper Hill', 'Waiyaki Way Interchange']
  return {
    id: assetId, node_name: names[Math.floor(Math.random() * names.length)], system_type: types[Math.floor(Math.random() * types.length)], stress,
    classification: stress >= 80 ? 'critical' : stress >= 60 ? 'warning' : stress >= 40 ? 'advisory' : 'nominal', lng, lat, timeseries,
    explanation: `Stress level attributed to ${stress >= 60 ? 'peak-hour demand exceeding design capacity.' : 'normal operational variance.'}`,
    recommendation: stress >= 80 ? 'Immediately reroute 15% of load to auxiliary nodes.' : stress >= 60 ? 'Schedule preventive maintenance within 48 hours.' : 'Continue routine monitoring.',
  }
}

function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function mapGeoJsonToPoints(features: any[]): StressPoint[] {
  if (!features || !Array.isArray(features)) return []
  return features.map((f: any) => {
    const coords = f.geometry?.coordinates || [0, 0]
    const p = f.properties || {}
    return {
      lng: coords[0],
      lat: coords[1],
      stress: p.stress || 50,
      asset_id: p.asset_id || `AST-${Math.floor(Math.random() * 9000)}`,
      classification: p.classification || p.severity || 'advisory',
      recurring: p.recurring || (p.stress >= 60),
    }
  })
}

export default function StressMap() {
  const [searchParams, setSearchParams] = useSearchParams()
  const deckRef = useRef<DeckGLRef>(null)
  const mapRef = useRef<MapRef>(null)

  const [viewState, setViewState] = useState({
    latitude: Number(searchParams.get('lat')) || NAIROBI_CENTER.lat,
    longitude: Number(searchParams.get('lng')) || NAIROBI_CENTER.lng,
    zoom: Number(searchParams.get('zoom')) || DEFAULT_ZOOM,
    bearing: 0, pitch: 0,
  })

  const handleViewStateChange = useCallback(({ viewState: vs }: { viewState: { latitude: number; longitude: number; zoom: number } }) => {
    setViewState(prev => ({ ...prev, ...vs }))
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('lat', vs.latitude.toFixed(6))
      next.set('lng', vs.longitude.toFixed(6))
      next.set('zoom', vs.zoom.toFixed(1))
      return next
    }, { replace: true })
  }, [setSearchParams])

  const [layerStates, setLayerStates] = useState<LayerState[]>(defaultLayers)
  const toggleLayer = useCallback((id: string) => {
    setLayerStates(prev => prev.map(l => (l.id === id ? { ...l, visible: !l.visible } : l)))
  }, [])

  const [selectedAsset, setSelectedAsset] = useState<AssetDetail | null>(null)
  const [pulseTick, setPulseTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setPulseTick(t => t + 1), 1200)
    return () => clearInterval(id)
  }, [])

  const [stressPoints, setStressPoints] = useState<StressPoint[]>([])
  const [waterMains] = useState<WaterMainLine[]>(generateWaterMains)
  const [gridCells, setGridCells] = useState<GridCellFeature[]>([])

  // Fetch stress points from backend with infrastructure type filter
  useEffect(() => {
    const activeSystem = searchParams.get('system') || 'power'

    api.spatial.stressPoints(activeSystem, 60)
      .then(data => {
        if (data?.features) {
          setStressPoints(mapGeoJsonToPoints(data.features))
        }
      })
      .catch(() => {})
  }, [searchParams])

  // Fetch grid cells for the grid layer
  useEffect(() => {
    const activeSystem = searchParams.get('system') || 'power'
    api.spatial.stressHeatmap(activeSystem, '36.65,-1.43,37.10,-0.98')
      .then(data => { if (data?.features) setGridCells(data.features as unknown as GridCellFeature[]) })
      .catch(() => {})
  }, [searchParams])

  const layers = useMemo(() => {
    const result: any[] = []
    if (layerStates.find(l => l.id === 'heatmap')?.visible) {
      result.push(new HeatmapLayer({
        id: 'stress-heatmap', data: stressPoints,
        getPosition: (d: any) => [d.lng, d.lat],
        getWeight: (d: any) => d.stress,
        radiusPixels: 50, intensity: 0.7, threshold: 0.05,
        colorRange: [[34, 197, 94, 0], [34, 197, 94, 100], [132, 204, 22, 150], [234, 179, 8, 180], [245, 158, 11, 200], [239, 68, 68, 220]],
        aggregation: 'SUM', opacity: 0.8,
      }))
    }
    if (layerStates.find(l => l.id === 'scatterplot')?.visible) {
      const pulsePhase = pulseTick % 2 === 0 ? 1 : 0.7
      result.push(new ScatterplotLayer({
        id: 'stress-points', data: stressPoints,
        getPosition: (d: any) => [d.lng, d.lat],
        getRadius: (d: any) => (d.recurring ? 18 * pulsePhase : Math.max(4, d.stress * 0.15)),
        getFillColor: (d: any) => (d.recurring ? [234, 179, 8, 220] : stressToColorArray(d.stress)),
        radiusMinPixels: 3, radiusMaxPixels: 22,
        pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 80],
      }))
    }
    if (layerStates.find(l => l.id === 'waterMains')?.visible) {
      result.push(new LineLayer({
        id: 'water-mains', data: waterMains,
        getSourcePosition: (d: any) => d.coordinates[0],
        getTargetPosition: (d: any) => d.coordinates[d.coordinates.length - 1],
        getWidth: 3, getColor: (d: any) => stressToColorArray(d.stress),
        pickable: true,
      }))
    }
    if (layerStates.find(l => l.id === 'grid')?.visible && gridCells.length > 0) {
      result.push(new PolygonLayer({
        id: 'stress-grid', data: gridCells,
        getPolygon: (d: any) => d.geometry.coordinates,
        getFillColor: (d: any) => stressToColorArray(d.properties.stress),
        getElevation: (d: any) => d.properties.stress * 80,
        extruded: false, opacity: 0.5, pickable: true, wireframe: true,
        getLineColor: [255, 255, 255, 30], getLineWidth: 1,
      }))
    }
    return result
  }, [layerStates, stressPoints, waterMains, gridCells, pulseTick])

  const getTooltip = useCallback(({ object }: PickingInfo) => {
    if (!object) return null
    if (object.asset_id) {
      const safeAssetId = escapeHtml(String(object.asset_id))
      const safeClassification = escapeHtml(String(object.classification))
      return { html: `<div style="font-family:Inter,sans-serif;font-size:12px;color:#f1f5f9;background:#0f172a;padding:8px 12px;border-radius:6px;border:1px solid #1e293b"><div style="color:#94a3b8;font-size:10px;text-transform:uppercase">${safeClassification}</div><div style="font-weight:600">${safeAssetId}</div><div>Stress: <span style="font-weight:600">${object.stress}%</span></div></div>` }
    }
    if (object.name) {
      const safeName = escapeHtml(String(object.name))
      return { html: `<div style="font-family:Inter,sans-serif;font-size:12px;color:#f1f5f9;background:#0f172a;padding:8px 12px;border-radius:6px;border:1px solid #1e293b"><div style="color:#94a3b8;font-size:10px;text-transform:uppercase">Water Main</div><div style="font-weight:600">${safeName}</div></div>` }
    }
    if (object.properties?.stress !== undefined) {
      const safeStress = escapeHtml(String(object.properties.stress))
      return { html: `<div style="font-family:Inter,sans-serif;font-size:12px;color:#f1f5f9;background:#0f172a;padding:8px 12px;border-radius:6px;border:1px solid #1e293b"><div style="color:#94a3b8;font-size:10px;text-transform:uppercase">Grid Cell</div><div>Stress: <span style="font-weight:600">${safeStress}</span></div></div>` }
    }
    return null
  }, [])

  const handleClick = useCallback((info: PickingInfo) => {
    if (info.object?.asset_id) {
      setSelectedAsset(generateAssetDetail(info.object.asset_id, info.object.lat, info.object.lng, info.object.stress))
    }
  }, [])

  return (
    <div className="relative w-full h-[500px] lg:h-[600px] panel overflow-hidden">
      <DeckGL
        ref={deckRef}
        initialViewState={viewState}
        controller={{ dragRotate: false, touchRotate: false, keyboard: false }}
        layers={layers}
        onViewStateChange={handleViewStateChange}
        getTooltip={getTooltip}
        onClick={handleClick}
        pickingRadius={5}
      >
        <Map ref={mapRef} reuseMaps mapStyle={MAP_STYLE} attributionControl={false} />
      </DeckGL>

      <div className="absolute top-3 right-3 z-10 flex flex-col gap-1">
        <button onClick={() => { const next = Math.min(viewState.zoom + 1, 18); setViewState(p => ({ ...p, zoom: next })); setSearchParams(p => { const n = new URLSearchParams(p); n.set('zoom', next.toFixed(1)); return n }, { replace: true }) }} className="w-8 h-8 flex items-center justify-center bg-sindio-panel/90 text-sindio-text hover:text-white transition-colors rounded border border-sindio-border">
          <ZoomIn className="w-4 h-4" />
        </button>
        <button onClick={() => { const next = Math.max(viewState.zoom - 1, 4); setViewState(p => ({ ...p, zoom: next })); setSearchParams(p => { const n = new URLSearchParams(p); n.set('zoom', next.toFixed(1)); return n }, { replace: true }) }} className="w-8 h-8 flex items-center justify-center bg-sindio-panel/90 text-sindio-text hover:text-white transition-colors rounded border border-sindio-border">
          <ZoomOut className="w-4 h-4" />
        </button>
        <button onClick={() => { setViewState({ latitude: NAIROBI_CENTER.lat, longitude: NAIROBI_CENTER.lng, zoom: DEFAULT_ZOOM, bearing: 0, pitch: 0 }); setSearchParams({ lat: NAIROBI_CENTER.lat.toFixed(6), lng: NAIROBI_CENTER.lng.toFixed(6), zoom: String(DEFAULT_ZOOM) }, { replace: true }) }} className="w-8 h-8 flex items-center justify-center bg-sindio-panel/90 text-sindio-text hover:text-white transition-colors rounded border border-sindio-border" title="Reset view">
          <Home className="w-3.5 h-3.5" />
        </button>
      </div>

      <MapLegend toggles={layerStates} onToggle={toggleLayer} />

      {selectedAsset && (
        <>
          <div className="fixed inset-0 bg-black/40 z-40" onClick={() => setSelectedAsset(null)} />
          <StressDrawer asset={selectedAsset} onClose={() => setSelectedAsset(null)} />
        </>
      )}

      <style>{`@keyframes slide-in { from { transform: translateX(100%); } to { transform: translateX(0); } } .animate-slide-in { animation: slide-in 0.25s ease-out; }`}</style>
    </div>
  )
}
