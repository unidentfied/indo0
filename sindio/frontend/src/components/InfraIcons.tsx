import { Zap, Droplet, Route, Recycle, Footprints, Train, TrainFront, Plane, HelpCircle } from 'lucide-react'

const infraIcons: Record<string, React.ReactNode> = {
  power: <Zap className="w-4 h-4 text-yellow-400" />,
  water: <Droplet className="w-4 h-4 text-blue-400" />,
  roads: <Route className="w-4 h-4 text-emerald-400" />,
  solid_waste: <Recycle className="w-4 h-4 text-purple-400" />,
  sidewalks: <Footprints className="w-4 h-4 text-orange-400" />,
  lrt: <Train className="w-4 h-4 text-cyan-400" />,
  sgr: <TrainFront className="w-4 h-4 text-teal-400" />,
  airports: <Plane className="w-4 h-4 text-sky-400" />,
}

export function InfraIcon({ type }: { type: string }) {
  return <>{infraIcons[type] || <HelpCircle className="w-4 h-4 text-sindio-muted" />}</>
}

export default infraIcons
