import axios from 'axios'

import type { AuditLog, PodStatus, Project, ProjectCreatePayload, ProjectEvent } from './types'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000',
})

async function request<T>(method: 'GET' | 'POST' | 'DELETE', url: string, data?: unknown): Promise<T> {
  const response = await api.request<T>({ method, url, ...(data === undefined ? {} : { data }) })
  return response.data
}

export function getProjects(): Promise<Project[]> {
  return request<Project[]>('GET', '/api/projects')
}

export function createProject(payload: ProjectCreatePayload): Promise<Project> {
  return request<Project>('POST', '/api/projects', payload)
}

function projectPath(id: string): string {
  return `/api/projects/${encodeURIComponent(id)}`
}

export function getProject(id: string): Promise<Project> {
  return request<Project>('GET', projectPath(id))
}

export function getPods(id: string): Promise<PodStatus[]> {
  return request<PodStatus[]>('GET', `${projectPath(id)}/pods`)
}

export function getEvents(id: string): Promise<ProjectEvent[]> {
  return request<ProjectEvent[]>('GET', `${projectPath(id)}/events`)
}

export function getAuditLogs(id: string): Promise<AuditLog[]> {
  return request<AuditLog[]>('GET', `${projectPath(id)}/audit-logs`)
}

export function syncProjectStatus(id: string): Promise<Project> {
  return request<Project>('POST', `${projectPath(id)}/sync-status`)
}

export function deleteProject(id: string): Promise<Project> {
  return request<Project>('DELETE', projectPath(id))
}
