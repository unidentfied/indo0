import { Routes, Route } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import LandingPage from './pages/LandingPage'
import Dashboard from './pages/Dashboard'

function App() {
  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-sindio-dark text-sindio-text font-sans flex flex-col">
        <Navbar />
        <div className="flex-1 flex">
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/dashboard" element={<Dashboard />} />
          </Routes>
        </div>
        <Footer />
      </div>
    </ErrorBoundary>
  )
}

export default App
