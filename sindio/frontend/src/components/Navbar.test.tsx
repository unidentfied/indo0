import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Navbar from './Navbar'

describe('Navbar', () => {
  it('renders the Sindio brand name', () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    )
    expect(screen.getByText(/Sindio/i)).toBeInTheDocument()
  })

  it('contains a link to the dashboard', () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    )
    const link = screen.getByRole('link', { name: /Dashboard/i })
    expect(link).toBeInTheDocument()
    expect(link.getAttribute('href')).toBe('/dashboard')
  })
})
