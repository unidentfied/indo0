import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

describe('App', () => {
  it('renders landing page at / route', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading.textContent).toContain('Infrastructure Resilience')
  })

  it('renders dashboard at /dashboard route', async () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <App />
      </MemoryRouter>
    )
    const heading = await screen.findByText(/Power System Analysis/i, {}, { timeout: 10000 })
    expect(heading).toBeInTheDocument()
  })
})
