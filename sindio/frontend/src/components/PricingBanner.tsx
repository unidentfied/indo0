import { useState } from 'react'

export default function PricingBanner({ openSignup }: { openSignup: () => void }) {
  const [agreed, setAgreed] = useState(false)
  const monthlyPrice = 83800 // Ksh per month
  const yearlyPrice = Math.round(monthlyPrice * 12 * 0.8) // ~20% discount

  return (
    <section className="bg-sindio-panel border border-sindio-border rounded-lg p-6 max-w-2xl mx-auto my-8 shadow-lg">
      <h2 className="text-2xl font-bold text-center mb-4 text-sindio-accent">
        Choose Your Plan
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="border border-sindio-border rounded-lg p-4 text-center">
          <h3 className="text-lg font-medium mb-2 text-sindio-muted">Monthly</h3>
          <p className="text-3xl font-bold text-sindio-accent">{monthlyPrice.toLocaleString()} KSh</p>
          <p className="text-xs text-sindio-muted mt-1">per month</p>
        </div>
        <div className="border border-sindio-border rounded-lg p-4 text-center">
          <h3 className="text-lg font-medium mb-2 text-sindio-muted">Yearly (≈20% off)</h3>
          <p className="text-3xl font-bold text-sindio-accent">{yearlyPrice.toLocaleString()} KSh</p>
          <p className="text-xs text-sindio-muted mt-1">billed annually</p>
        </div>
      </div>
      <div className="flex items-center justify-center mb-4">
        <input
          type="checkbox"
          id="terms"
          className="mr-2"
          checked={agreed}
          onChange={() => setAgreed(!agreed)}
        />
        <label htmlFor="terms" className="text-sm text-sindio-muted cursor-pointer">
          I agree to the <a href="/terms" className="underline text-sindio-accent hover:text-sindio-accent-hover">Terms & Conditions</a>
        </label>
      </div>
      <button
        className={`btn-primary w-full ${!agreed ? 'opacity-50 cursor-not-allowed' : ''}`}
        disabled={!agreed}
        onClick={() => openSignup()}
      >
        Sign Up
      </button>
    </section>
  )
}
