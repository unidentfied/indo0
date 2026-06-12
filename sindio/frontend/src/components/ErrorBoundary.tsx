import React, { Component, ErrorInfo, ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { hasError: boolean; error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-sindio-dark text-sindio-text">
          <div className="panel p-8 max-w-lg text-center">
            <h2 className="text-xl font-bold text-sindio-critical mb-4">Application Error</h2>
            <pre className="text-xs text-sindio-muted bg-sindio-panel p-4 rounded overflow-auto max-h-64 text-left">
              {this.state.error?.message}
            </pre>
            <button
              onClick={() => window.location.reload()}
              className="btn-primary mt-4"
            >
              Reload Page
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
