import { useState, useEffect } from 'react'
import { api } from '../services/api'
import { MapPin, ChevronDown } from 'lucide-react'

interface CitySwitcherProps {
  activeCity: string
  onCityChange: (slug: string) => void
}

interface CityInfo {
  slug: string
  name: string
  country: string
  is_active: boolean
}

export default function CitySwitcher({ activeCity, onCityChange }: CitySwitcherProps) {
  const [cities, setCities] = useState<CityInfo[]>([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    api.cities.list().then(setCities).catch(() => {})
  }, [])

  const active = cities.find(c => c.slug === activeCity) || { slug: activeCity, name: activeCity, country: '', is_active: true }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-sm text-sindio-muted hover:text-white transition-colors bg-sindio-dark rounded-lg px-2.5 py-1.5 border border-sindio-border"
      >
        <MapPin className="w-3.5 h-3.5 text-sindio-accent" />
        <span className="max-w-[100px] truncate">{active.name}</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 bg-sindio-panel border border-sindio-border rounded-lg shadow-xl z-50 min-w-[180px] overflow-hidden">
            {cities.map((city) => (
              <button
                key={city.slug}
                type="button"
                onClick={() => {
                  onCityChange(city.slug)
                  setOpen(false)
                }}
                className={`w-full text-left px-3 py-2 text-sm transition-colors hover:bg-sindio-accent/10 flex items-center justify-between ${
                  city.slug === activeCity ? 'text-sindio-accent bg-sindio-accent/5' : 'text-sindio-muted'
                }`}
              >
                <span>{city.name}</span>
                <span className="text-xs opacity-60">{city.country}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
