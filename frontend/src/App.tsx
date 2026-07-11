import { Navigate, Route, Routes } from 'react-router-dom'

import { NewProjectPage } from './pages/NewProject'
import { ProjectDetailPage } from './pages/ProjectDetail'
import { ProjectListPage } from './pages/ProjectList'
import './App.css'

export default function App() {
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
      <Routes>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectListPage />} />
        <Route path="/projects/new" element={<NewProjectPage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
      </Routes>
    </main>
  )
}