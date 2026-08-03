import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-sindio-muted text-sm">
        Loading...
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/" state={{ requireAuth: true, from: location.pathname }} replace />
  }

  return <>{children}</>
}
