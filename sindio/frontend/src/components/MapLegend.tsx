interface LayerToggle {
  id: string
  label: string
  color: string
  visible: boolean
}

interface MapLegendProps {
  toggles: LayerToggle[]
  onToggle: (id: string) => void
}

const stressColors = [
  { label: '0–20', color: '#22c55e' },
  { label: '20–40', color: '#84cc16' },
  { label: '40–60', color: '#eab308' },
  { label: '60–80', color: '#f97316' },
  { label: '80–100', color: '#ef4444' },
]

export default function MapLegend({ toggles, onToggle }: MapLegendProps) {
  return (
    <div className="absolute bottom-4 left-4 z-10 panel p-3 text-xs space-y-3 min-w-[180px] bg-sindio-panel/95 backdrop-blur">
      <div className="font-semibold uppercase tracking-wider text-sindio-muted text-[10px] mb-2">Layers</div>
      {toggles.map(t => (
        <label
          key={t.id}
          className="flex items-center gap-2 cursor-pointer hover:text-sindio-text transition-colors"
        >
          <input
            type="checkbox"
            checked={t.visible}
            onChange={() => onToggle(t.id)}
            className="accent-sindio-accent"
          />
          <span
            className="w-3 h-3 rounded-sm inline-block flex-shrink-0"
            style={{ backgroundColor: t.color }}
          />
          <span className={t.visible ? 'text-sindio-text' : 'text-sindio-muted'}>{t.label}</span>
        </label>
      ))}
      <div className="pt-2 border-t border-sindio-border">
        <div className="font-semibold uppercase tracking-wider text-sindio-muted text-[10px] mb-1.5">
          Stress Scale
        </div>
        <div className="space-y-0.5">
          {stressColors.map(s => (
            <div key={s.label} className="flex items-center gap-2">
              <span className="w-8 h-2 rounded" style={{ backgroundColor: s.color }} />
              <span>{s.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
