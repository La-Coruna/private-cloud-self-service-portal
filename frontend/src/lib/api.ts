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

export function getProject(id: number): Promise<Project> {
  return request<Project>('GET', `/api/projects/${id}`)
}

export function getPods(id: number): Promise<PodStatus[]> {
  return request<PodStatus[]>('GET', `/api/projects/${id}/pods`)
}

export function getEvents(id: number): Promise<ProjectEvent[]> {
  return request<ProjectEvent[]>('GET', `/api/projects/${id}/events`)
}

export function getAuditLogs(id: number): Promise<AuditLog[]> {
  return request<AuditLog[]>('GET', `/api/projects/${id}/audit-logs`)
}

export function syncProjectStatus(id: number): Promise<Project> {
  return request<Project>('POST', `/api/projects/${id}/sync-status`)
}

export function deleteProject(id: number): Promise<Project> {
  return request<Project>('DELETE', `/api/projects/${id}`)
}