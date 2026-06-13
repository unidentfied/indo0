import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MetricCard from './MetricCard'

describe('MetricCard', () => {
  const mockProps = {
    label: 'Grid Stability',
    value: '99.7%',
    delta: '+0.2%',
    status: 'good' as const,
  }

  it('renders label and value', () => {
    render(<MetricCard {...mockProps} />)
    expect(screen.getByText('Grid Stability')).toBeInTheDocument()
    expect(screen.getByText('99.7%')).toBeInTheDocument()
  })

  it('renders delta text', () => {
    render(<MetricCard {...mockProps} />)
    expect(screen.getByText('+0.2%')).toBeInTheDocument()
  })

  it('renders with warning status', () => {
    render(<MetricCard {...mockProps} status="warning" />)
    expect(screen.getByText('Grid Stability')).toBeInTheDocument()
  })

  it('renders with critical status', () => {
    render(<MetricCard {...mockProps} status="advisory" />)
    expect(screen.getByText('Grid Stability')).toBeInTheDocument()
  })
})
