import { Navigate, Route, Routes } from 'react-router-dom'

import { PlatformStatusBanner } from './components/PlatformStatusBanner'
import { usePlatformStatus } from './hooks/usePlatformStatus'
import type { PlatformStatus } from './lib/types'
import { NewProjectPage } from './pages/NewProject'
import { ProjectDetailPage } from './pages/ProjectDetail'
import { ProjectListPage } from './pages/ProjectList'
import './App.css'

export default function App() {
  const platformStatusQuery = usePlatformStatus()
  const platformStatus: PlatformStatus | undefined = platformStatusQuery.isError
    ? {
        status: 'UNAVAILABLE',
        message: '플랫폼 상태를 확인할 수 없습니다. 잠시 후 자동으로 다시 확인합니다.',
        creation_allowed: false,
        checked_at: platformStatusQuery.data?.checked_at ?? '',
      }
    : platformStatusQuery.data

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Private Cloud</p>
          <strong>Self-Service Portal</strong>
        </div>
        <nav>
          <a href="/projects">Projects</a>
          <a href="/projects/new">New</a>
        </nav>
      </header>
      {platformStatus && <PlatformStatusBanner status={platformStatus} />}
      <Routes>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectListPage />} />
        <Route
          path="/projects/new"
          element={<NewProjectPage creationAllowed={platformStatus?.status === 'AVAILABLE'} />}
        />
        <Route
          path="/projects/:id"
          element={<ProjectDetailPage platformStatus={platformStatus?.status} />}
        />
      </Routes>
    </main>
  )
}