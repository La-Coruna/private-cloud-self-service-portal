import { describe, expect, it, vi } from 'vitest'

import {
  createProject,
  deleteProject,
  getAuditLogs,
  getEvents,
  getPods,
  getProject,
  getProjects,
  syncProjectStatus,
} from './lib/api'

const request = vi.hoisted(() => vi.fn())

vi.mock('axios', () => ({
  default: {
    create: () => ({ request }),
  },
}))

describe('project API client', () => {
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
    await getProject(3)
    await getPods(3)
    await getEvents(3)
    await getAuditLogs(3)
    await syncProjectStatus(3)
    await deleteProject(3)

    expect(request).toHaveBeenNthCalledWith(1, { method: 'GET', url: '/api/projects' })
    expect(request).toHaveBeenNthCalledWith(2, {
      method: 'POST',
      url: '/api/projects',
      data: expect.objectContaining({ service_name: 'web' }),
    })
    expect(request).toHaveBeenNthCalledWith(3, { method: 'GET', url: '/api/projects/3' })
    expect(request).toHaveBeenNthCalledWith(4, { method: 'GET', url: '/api/projects/3/pods' })
    expect(request).toHaveBeenNthCalledWith(5, { method: 'GET', url: '/api/projects/3/events' })
    expect(request).toHaveBeenNthCalledWith(6, { method: 'GET', url: '/api/projects/3/audit-logs' })
    expect(request).toHaveBeenNthCalledWith(7, { method: 'POST', url: '/api/projects/3/sync-status' })
    expect(request).toHaveBeenNthCalledWith(8, { method: 'DELETE', url: '/api/projects/3' })
  })
})
