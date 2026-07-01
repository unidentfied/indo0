import { ArrowLeft, Users } from 'lucide-react'
import { Link } from 'react-router-dom'

const team = [
  {
    name: 'Jordan Mafumbo',
    role: 'Founder & Principal Engineer',
    bio: 'Civil engineer with over 7 years experience in high-rise design, and urban planning across South Africa, East Africa, and Europe. Holds fellowships with IRCICA, Emergent Ventures, SPAB. Holds membership positions with INTBAU, The Georgian Group, The Commonwealth Heritage Forum. Writes extensively (articles and research papers) on infrastructure-adjacent urbanism in the region: domestic connectivity, inclusive urban planning, AI-based flood prediction, transport corridor pressure, across Kenya, Ethiopia, and Uganda.',
  },
  {
    name: 'Amina Wanjiku',
    role: 'Urban Systems Analyst',
    bio: 'Geospatial data scientist with expertise in urban morphology and infrastructure resilience modelling. Specialises in integrating GIS datasets with machine learning pipelines for predictive urban planning. Previously contributed to the Nairobi Integrated Urban Development Master Plan and the Lamu Port-South Sudan-Ethiopia Transport Corridor assessment.',
  },
]

export default function PeoplePage() {
  return (
    <div className="flex-1 p-4 sm:p-6 lg:p-8 max-w-4xl mx-auto">
      <Link
        to="/"
        className="inline-flex items-center gap-2 text-sm text-sindio-muted hover:text-sindio-accent transition-colors mb-8"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Home
      </Link>

      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-lg bg-sindio-accent/10 flex items-center justify-center">
          <Users className="w-5 h-5 text-sindio-accent" />
        </div>
        <h1 className="text-3xl font-bold">People</h1>
      </div>
      <p className="text-sindio-muted text-sm mb-10 max-w-lg leading-relaxed">
        Meet the team building Sindio's infrastructure intelligence platform.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {team.map((person) => (
          <div key={person.name} className="panel p-6">
            <div className="w-16 h-16 rounded-full bg-sindio-accent/10 border border-sindio-border flex items-center justify-center mb-4">
              <span className="text-xl font-bold text-sindio-accent">
                {person.name.split(' ').map(n => n[0]).join('')}
              </span>
            </div>
            <h2 className="text-lg font-semibold mb-1">{person.name}</h2>
            <p className="text-xs uppercase tracking-wider text-sindio-accent font-medium mb-3">{person.role}</p>
            <p className="text-sm text-sindio-muted leading-relaxed">{person.bio}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
