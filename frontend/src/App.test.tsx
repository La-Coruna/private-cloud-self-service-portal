import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const apiMocks = vi.hoisted(() => {
  const project = {
    id: 1,
    service_name: 'demo-api',
    environment: 'staging' as const,
    image: 'nginx:latest',
    replicas: 1,
    cpu_request: '100m',
    cpu_limit: '500m',
    memory_request: '128Mi',
    memory_limit: '512Mi',
    expose_external: true,
    namespace: 'demo-api-staging',
    ingress_host: 'demo-api-staging.localtest.me',
    status: 'RUNNING' as const,
    error_message: null,
    created_at: '2026-07-11T09:00:00',
    updated_at: '2026-07-11T09:00:00',
  }

  return {
    createProject: vi.fn(),
    deleteProject: vi.fn(() => Promise.resolve(project)),
    getAuditLogs: vi.fn(() => Promise.resolve([])),
    getEvents: vi.fn(() => Promise.resolve([])),
    getPods: vi.fn(() =>
      Promise.resolve([
        {
          name: 'demo-api-abc',
          namespace: 'demo-api-staging',
          phase: 'Running',
          pod_ip: '10.244.0.10',
          node_name: 'kind-worker',
          start_time: '2026-07-11T09:00:00',
          containers: [
            {
              name: 'demo-api',
              image: 'nginx:latest',
              ready: true,
              restart_count: 0,
              state: 'running',
              reason: null,
              message: null,
            },
          ],
        },
      ]),
    ),
    getProject: vi.fn(() => Promise.resolve(project)),
    getProjects: vi.fn(() => Promise.resolve([project])),
    syncProjectStatus: vi.fn(() => Promise.resolve(project)),
  }
})

vi.mock('./lib/api', () => apiMocks)

function renderApp(path = '/projects') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('project dashboard routes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the project list with ingress information', async () => {
    renderApp('/projects')

    expect(await screen.findByText('demo-api')).toBeInTheDocument()
    expect(screen.getByText('RUNNING')).toBeInTheDocument()
    expect(screen.getByText('demo-api-staging.localtest.me')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /새 프로젝트/i })).toHaveAttribute(
      'href',
      '/projects/new',
    )
  })

  it('syncs project status from the detail page', async () => {
    const user = userEvent.setup()
    renderApp('/projects/1')

    expect(await screen.findByRole('heading', { name: 'demo-api' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /상태 새로고침/i }))

    await waitFor(() => expect(apiMocks.syncProjectStatus).toHaveBeenCalledWith(1))
  })
})
