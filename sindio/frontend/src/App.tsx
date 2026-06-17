import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import LandingPage from './pages/LandingPage'

const Dashboard = lazy(() => import('./pages/Dashboard'))

function App() {
  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-sindio-dark text-sindio-text font-sans flex flex-col">
        <Navbar />
        <div className="flex-1 flex">
          <Suspense
            fallback={
              <div className="flex-1 flex items-center justify-center text-sindio-muted text-sm">
                Loading dashboard...
              </div>
            }
          >
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/dashboard" element={<Dashboard />} />
            </Routes>
          </Suspense>
        </div>
        <Footer />
      </div>
    </ErrorBoundary>
  )
}

export default App
