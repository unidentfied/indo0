import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MetricCard from './MetricCard'

describe('MetricCard', () => {
  const mockMetric = {
    label: 'Grid Stability',
    value: '99.7%',
    delta: '+0.2%',
    status: 'good' as const,
  }

  it('renders label and value', () => {
    render(<MetricCard metric={mockMetric} />)
    expect(screen.getByText('Grid Stability')).toBeInTheDocument()
    expect(screen.getByText('99.7%')).toBeInTheDocument()
  })

  it('renders delta text', () => {
    render(<MetricCard metric={mockMetric} />)
    expect(screen.getByText('+0.2%')).toBeInTheDocument()
  })

  it('renders with warning status', () => {
    render(<MetricCard metric={{ ...mockMetric, status: 'warning' }} />)
    expect(screen.getByText('Grid Stability')).toBeInTheDocument()
  })

  it('renders with critical status', () => {
    render(<MetricCard metric={{ ...mockMetric, status: 'critical' }} />)
    expect(screen.getByText('Grid Stability')).toBeInTheDocument()
  })
})
