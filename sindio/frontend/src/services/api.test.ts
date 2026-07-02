/**
 * Tests for the centralized API client.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from './api'

describe('api client', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('health returns status', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const result = await api.health()
    expect(result.status).toBe('ok')
    expect(fetchSpy).toHaveBeenCalledWith('/api/health', expect.any(Object))
  })

  it('dashboard.metrics calls correct path', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          { label: 'Grid Stability', value: '95%', status: 'good' },
          { label: 'Current Load', value: '1,200 MW', status: 'warning' },
          { label: 'Active Nodes', value: '42', status: 'good' },
          { label: 'Latency', value: '12ms', status: 'good' },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const result = await api.dashboard.metrics()
    expect(Array.isArray(result)).toBe(true)
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/dashboard/metrics', expect.any(Object))
  })

  it('v1.alerts returns envelope with alerts array', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ alerts: [{ id: '1', level: 'critical', title: 'Test', description: '', category: 'power', created_at: '' }] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const result = await api.v1.alerts()
    expect(result.alerts).toHaveLength(1)
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/alerts', expect.any(Object))
  })

  it('v1.nextUpdates returns envelope with updates array', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ updates: [{ infrastructure_type: 'power', next_update_seconds: 30, data_freshness_seconds: 30, source: 'test' }] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const result = await api.v1.nextUpdates()
    expect(result.updates).toHaveLength(1)
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/next_updates', expect.any(Object))
  })

  it('throws on non-200 response', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response('Not Found', { status: 404 }),
    )

    await expect(api.dashboard.alerts()).rejects.toThrow('API 404')
  })

  it('simulations.run posts to correct URL', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          task_id: 'abc-123',
          network_type: 'power',
          stress_factor: 'peak',
          failure_risk: 'low',
          recommendation: 'ok',
          status: 'running',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const result = await api.simulations.run('power')
    expect(result.task_id).toBe('abc-123')
    expect(result.network_type).toBe('power')
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/simulations/run?network=power',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
