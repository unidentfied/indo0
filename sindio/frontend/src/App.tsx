import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import LandingPage from './pages/LandingPage'
import PlaceholderPage from './pages/PlaceholderPage'
import NotFoundPage from './pages/NotFoundPage'

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
              
              {/* Auxiliary Footer Routes */}
              <Route path="/privacy" element={<PlaceholderPage title="Privacy Policy" />} />
              <Route path="/cookies" element={<PlaceholderPage title="Cookie Policy" />} />
              <Route path="/terms" element={<PlaceholderPage title="Terms & Conditions" />} />
              <Route path="/status" element={<PlaceholderPage title="Service Status" />} />
              <Route path="/careers" element={<PlaceholderPage title="Careers" />} />
              <Route path="/faq" element={<PlaceholderPage title="Frequently Asked Questions" />} />
              <Route path="/contact" element={<PlaceholderPage title="Contact Us" />} />
              <Route path="/press" element={<PlaceholderPage title="Press" />} />
              <Route path="/about" element={<PlaceholderPage title="About Sindio" />} />
              
              {/* Fallback */}
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </Suspense>
        </div>
        <Footer />
      </div>
    </ErrorBoundary>
  )
}

export default App
