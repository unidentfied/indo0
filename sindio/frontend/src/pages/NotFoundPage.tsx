import { AlertTriangle, Home } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 bg-sindio-dark text-sindio-text text-center border-l border-sindio-border">
      <div className="w-20 h-20 rounded-2xl bg-sindio-panel border border-sindio-border flex items-center justify-center mb-6 shadow-xl shadow-red-500/10">
        <AlertTriangle className="w-10 h-10 text-red-400" />
      </div>
      
      <h1 className="text-4xl font-bold tracking-tight mb-2">404</h1>
      <h2 className="text-xl font-medium text-sindio-muted mb-4">Route Not Resolvable</h2>
      <p className="text-sindio-muted/80 max-w-sm mx-auto leading-relaxed mb-8">
        The requested endpoint or resource does not exist in the current spatial index or routing manifest.
      </p>
      
      <Link 
        to="/" 
        className="btn-primary"
      >
        <Home className="w-4 h-4 mr-2" />
        Return Home
      </Link>
    </div>
  )
}
