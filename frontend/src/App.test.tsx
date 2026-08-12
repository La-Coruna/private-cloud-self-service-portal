import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { AuditLog, PlatformStatus } from './lib/types'

const apiMocks = vi.hoisted(() => {
  const project = {
    id: 'demo-api-staging',
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
    getAuditLogs: vi.fn((): Promise<AuditLog[]> => Promise.resolve([])),
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
    getPlatformStatus: vi.fn((): Promise<PlatformStatus> =>
      Promise.resolve({
        status: 'AVAILABLE',
        message: 'GKE workload capacity is available',
        creation_allowed: true,
        checked_at: '2026-08-12T10:00:00',
      }),
    ),
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

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the project list with ingress information', async () => {
    renderApp('/projects')

    expect(await screen.findByText('demo-api')).toBeInTheDocument()
    expect(screen.getByText('RUNNING')).toBeInTheDocument()
    expect(screen.getByText('demo-api-staging.localtest.me')).toBeInTheDocument()
    expect(screen.getByText('Created at (KST)')).toBeInTheDocument()
    expect(screen.getByText(/KST$/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '\uc0c8 \ud504\ub85c\uc81d\ud2b8' })).toHaveAttribute(
      'href',
      '/projects/new',
    )
  })


  it('shows demo input rules on the new project page', async () => {
    const user = userEvent.setup()
    renderApp('/projects/new')

    const toggle = screen.getByRole('button', { name: '\uc785\ub825 \uaddc\uce59 \ubcf4\uae30' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('\uacf5\uac1c \ub370\ubaa8 \uc785\ub825 \uaddc\uce59')).toBeInTheDocument()
    expect(screen.getAllByText(/nginx:latest, httpd:alpine/).length).toBeGreaterThan(0)
  })

  it('renders backend create errors on the new project page', async () => {
    const user = userEvent.setup()
    apiMocks.createProject.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed',
      response: {
        status: 409,
        data: { detail: 'Demo mode replicas cannot exceed 1' },
      },
    })
    renderApp('/projects/new')

    await user.type(screen.getByLabelText(/Service name/i), 'demo-limit')
    await user.click(screen.getByRole('button', { name: '\uc0dd\uc131' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Demo mode replicas cannot exceed 1')
    expect(screen.getAllByText('Demo mode replicas cannot exceed 1')).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveTextContent('\ud504\ub85c\uc81d\ud2b8\ub97c \uc0dd\uc131\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4')
  })

  it('syncs project status from the detail page', async () => {
    const user = userEvent.setup()
    renderApp('/projects/demo-api-staging')

    expect(await screen.findByRole('heading', { name: 'demo-api' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Refresh status/i }))

    await waitFor(() => expect(apiMocks.syncProjectStatus).toHaveBeenCalledWith('demo-api-staging'))
  })

  it('shows recovery status and disables project creation while GKE workloads recover', async () => {
    apiMocks.getPlatformStatus.mockResolvedValueOnce({
      status: 'RECOVERING',
      message: 'Ready nodes are not available yet',
      creation_allowed: false,
      checked_at: '2026-08-12T10:00:00',
    })

    renderApp('/projects/new')

    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent('GKE 워크로드 복구 중')
    expect(banner).toHaveTextContent('Ready nodes are not available yet')
    expect(banner).toHaveTextContent('2026')
    expect(screen.getByRole('button', { name: '생성' })).toBeDisabled()
  })

  it('keeps project and audit data visible when Pod data is temporarily unavailable', async () => {
    apiMocks.getPods.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed',
      response: {
        status: 503,
        data: {
          error: {
            code: 'GKE_UNAVAILABLE',
            message: 'GKE 상태를 일시적으로 확인할 수 없습니다.',
            detail: 'Kubernetes API connection failed',
          },
        },
      },
    })
    apiMocks.getAuditLogs.mockResolvedValueOnce([
      {
        id: 'audit-1',
        project_id: 'demo-api-staging',
        action: 'PROJECT_CREATED',
        status: 'SUCCEEDED',
        message: 'Project saved in Firestore',
        created_at: '2026-07-11T09:00:00',
      },
    ])

    renderApp('/projects/demo-api-staging')

    expect(await screen.findByRole('heading', { name: 'demo-api' })).toBeInTheDocument()
    expect(await screen.findByText('PROJECT_CREATED')).toBeInTheDocument()
    expect(screen.getByText(/Pod 상태를 일시적으로 확인할 수 없음/)).toBeInTheDocument()
  })

  it('disables delete and sync only when the platform is unavailable', async () => {
    apiMocks.getPlatformStatus
      .mockResolvedValueOnce({
        status: 'UNAVAILABLE',
        message: 'Kubernetes API is temporarily unavailable',
        creation_allowed: false,
        checked_at: '2026-08-12T10:00:00',
      })
      .mockResolvedValueOnce({
        status: 'RECOVERING',
        message: 'Ready nodes are not available yet',
        creation_allowed: false,
        checked_at: '2026-08-12T10:00:15',
      })

    const unavailable = renderApp('/projects/demo-api-staging')

    expect(await screen.findByRole('alert')).toHaveTextContent('Kubernetes API is temporarily unavailable')
    expect(screen.getByRole('button', { name: 'Refresh status' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()

    unavailable.unmount()
    renderApp('/projects/demo-api-staging')

    expect(await screen.findByRole('status')).toHaveTextContent('Ready nodes are not available yet')
    expect(screen.getByRole('button', { name: 'Refresh status' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled()
  })

  it('removes the recovery banner after the 15-second platform status poll succeeds', async () => {
    vi.useFakeTimers()
    apiMocks.getPlatformStatus.mockResolvedValueOnce({
      status: 'RECOVERING',
      message: 'Ready nodes are not available yet',
      creation_allowed: false,
      checked_at: '2026-08-12T10:00:00',
    })

    renderApp('/projects')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByRole('status')).toHaveTextContent('GKE 워크로드 복구 중')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000)
    })
    await act(async () => {
      await Promise.resolve()
      await vi.advanceTimersByTimeAsync(1)
    })

    expect(apiMocks.getPlatformStatus).toHaveBeenCalledTimes(2)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
