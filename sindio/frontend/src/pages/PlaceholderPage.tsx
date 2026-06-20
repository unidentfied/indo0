import { ArrowRight, Settings } from 'lucide-react'
import { Link } from 'react-router-dom'

interface PlaceholderPageProps {
  title: string
  description?: string
}

export default function PlaceholderPage({ 
  title, 
  description = "This page is currently being provisioned for the next deployment cycle. Please check back later."
}: PlaceholderPageProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 bg-sindio-dark text-sindio-text text-center border-l border-sindio-border">
      <div className="w-16 h-16 rounded-full bg-sindio-panel border border-sindio-border flex items-center justify-center mb-6 shadow-xl shadow-sindio-accent/5">
        <Settings className="w-8 h-8 text-sindio-accent animate-[spin_10s_linear_infinite]" />
      </div>
      
      <h1 className="text-3xl font-bold tracking-tight mb-4">{title}</h1>
      <p className="text-sindio-muted max-w-md mx-auto leading-relaxed mb-8">
        {description}
      </p>
      
      <Link 
        to="/dashboard" 
        className="btn-primary"
      >
        Return to Dashboard
        <ArrowRight className="w-4 h-4 ml-2" />
      </Link>
    </div>
  )
}
