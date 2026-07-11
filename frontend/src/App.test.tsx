import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import App from './App'

vi.mock('./lib/api', () => ({
  getProjects: () =>
    Promise.resolve([
      {
        id: 1,
        service_name: 'demo-api',
        environment: 'staging',
        image: 'nginx:latest',
        replicas: 1,
        cpu_request: '100m',
        cpu_limit: '500m',
        memory_request: '128Mi',
        memory_limit: '512Mi',
        expose_external: true,
        namespace: 'demo-api-staging',
        ingress_host: 'demo-api-staging.localtest.me',
        status: 'RUNNING',
        error_message: null,
        created_at: '2026-07-11T09:00:00',
        updated_at: '2026-07-11T09:00:00',
      },
    ]),
}))

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
})
