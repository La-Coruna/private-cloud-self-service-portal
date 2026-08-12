import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createProject,
  deleteProject,
  getAuditLogs,
  getEvents,
  getPlatformStatus,
  getPods,
  getProject,
  getProjects,
  syncProjectStatus,
} from './lib/api'

const request = vi.hoisted(() => vi.fn())

vi.mock('axios', () => ({
  default: {
    create: () => ({ request }),
    isAxiosError: (error: unknown) =>
      typeof error === 'object' && error !== null && 'isAxiosError' in error && error.isAxiosError === true,
  },
}))

describe('project API client', () => {
  afterEach(() => {
    request.mockReset()
    vi.useRealTimers()
  })

  it('calls every backend project endpoint with the configured base URL', async () => {
    request.mockResolvedValue({ data: [] })

    await getProjects()
    await createProject({
      service_name: 'web',
      environment: 'staging',
      image: 'nginx:latest',
      replicas: 1,
      cpu_request: '100m',
      cpu_limit: '500m',
      memory_request: '128Mi',
      memory_limit: '512Mi',
      expose_external: true,
    })
    await getProject('demo-api-staging')
    await getPods('demo-api-staging')
    await getEvents('demo-api-staging')
    await getAuditLogs('demo-api-staging')
    await syncProjectStatus('demo-api-staging')
    await deleteProject('demo-api-staging')
    await getPlatformStatus()

    expect(request).toHaveBeenNthCalledWith(1, { method: 'GET', url: '/api/projects' })
    expect(request).toHaveBeenNthCalledWith(2, {
      method: 'POST',
      url: '/api/projects',
      data: expect.objectContaining({ service_name: 'web' }),
    })
    expect(request).toHaveBeenNthCalledWith(3, { method: 'GET', url: '/api/projects/demo-api-staging' })
    expect(request).toHaveBeenNthCalledWith(4, { method: 'GET', url: '/api/projects/demo-api-staging/pods' })
    expect(request).toHaveBeenNthCalledWith(5, { method: 'GET', url: '/api/projects/demo-api-staging/events' })
    expect(request).toHaveBeenNthCalledWith(6, { method: 'GET', url: '/api/projects/demo-api-staging/audit-logs' })
    expect(request).toHaveBeenNthCalledWith(7, { method: 'POST', url: '/api/projects/demo-api-staging/sync-status' })
    expect(request).toHaveBeenNthCalledWith(8, { method: 'DELETE', url: '/api/projects/demo-api-staging' })
    expect(request).toHaveBeenNthCalledWith(9, { method: 'GET', url: '/api/platform-status' })
  })

  it('retries a GET after a transient 503 and then succeeds', async () => {
    vi.useFakeTimers()
    request
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 503 } })
      .mockResolvedValueOnce({ data: [] })

    const projects = getProjects()
    void projects.catch(() => undefined)
    await vi.advanceTimersByTimeAsync(250)

    await expect(projects).resolves.toEqual([])
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('does not retry createProject after a transient failure', async () => {
    const transientError = { isAxiosError: true, response: { status: 503 } }
    request.mockRejectedValueOnce(transientError)

    await expect(
      createProject({
        service_name: 'web',
        environment: 'staging',
        image: 'nginx:latest',
        replicas: 1,
        cpu_request: '100m',
        cpu_limit: '500m',
        memory_request: '128Mi',
        memory_limit: '512Mi',
        expose_external: true,
      }),
    ).rejects.toBe(transientError)

    expect(request).toHaveBeenCalledTimes(1)
  })

  it('encodes string namespace IDs in project URLs', async () => {
    request.mockResolvedValue({ data: {} })

    await getProject('demo api/staging')

    expect(request).toHaveBeenCalledWith({ method: 'GET', url: '/api/projects/demo%20api%2Fstaging' })
  })
})
