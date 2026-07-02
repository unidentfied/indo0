import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import BackendBanner from './components/BackendBanner'
import { BackendStatusProvider } from './services/BackendStatus'
import LandingPage from './pages/LandingPage'
import FAQPage from './pages/FAQPage'
import PeoplePage from './pages/PeoplePage'
import PrivacyPage from './pages/PrivacyPage'
import CookiesPage from './pages/CookiesPage'
import TermsPage from './pages/TermsPage'
import NotFoundPage from './pages/NotFoundPage'

const Dashboard = lazy(() => import('./pages/Dashboard'))

function App() {
  return (
    <ErrorBoundary>
      <BackendStatusProvider>
        <div className="min-h-screen bg-sindio-dark text-sindio-text font-sans flex flex-col">
          <BackendBanner />
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
                <Route path="/privacy" element={<PrivacyPage />} />
                <Route path="/cookies" element={<CookiesPage />} />
                <Route path="/terms" element={<TermsPage />} />
                <Route path="/people" element={<PeoplePage />} />
                <Route path="/faq" element={<FAQPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </Suspense>
          </div>
          <Footer />
        </div>
      </BackendStatusProvider>
    </ErrorBoundary>
  )
}

export default App
