import { ArrowLeft, HelpCircle, Plus, Minus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { faqItems } from '../data/faq'

export default function FAQPage() {
  const [openFaq, setOpenFaq] = useState<number | null>(null)

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
          <HelpCircle className="w-5 h-5 text-sindio-accent" />
        </div>
        <h1 className="text-3xl font-bold">Frequently Asked Questions</h1>
      </div>
      <p className="text-sindio-muted text-sm mb-10 max-w-lg leading-relaxed">
        Everything you need to know about Sindio's infrastructure monitoring platform — from supported types to physics engines and integration options.
      </p>

      <div className="space-y-1">
        {faqItems.map((item, i) => (
          <div
            key={i}
            className="panel overflow-hidden border-b border-sindio-border/50 last:border-b-0"
          >
            <button
              onClick={() => setOpenFaq(openFaq === i ? null : i)}
              className="w-full flex items-center justify-between py-5 px-6 text-left group hover:bg-sindio-border/10 transition-colors"
            >
              <span className="text-sm font-semibold text-sindio-text group-hover:text-sindio-accent transition-colors pr-6">
                {item.q}
              </span>
              <span className="flex-shrink-0 text-sindio-muted group-hover:text-sindio-accent transition-colors">
                {openFaq === i ? (
                  <Minus className="w-5 h-5" />
                ) : (
                  <Plus className="w-5 h-5" />
                )}
              </span>
            </button>
            <div
              className={`overflow-hidden transition-all duration-300 ease-in-out ${
                openFaq === i ? 'max-h-96 pb-6 px-6' : 'max-h-0'
              }`}
            >
              <p className="text-sm text-sindio-muted leading-relaxed">
                {item.a}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
