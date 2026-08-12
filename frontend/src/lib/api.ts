import axios from 'axios'

import type { AuditLog, PlatformStatus, PodStatus, Project, ProjectCreatePayload, ProjectEvent } from './types'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
})

const readRetryDelays = [250, 1000]

function isTransientReadError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false
  return !error.response || [502, 503, 504].includes(error.response.status)
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function request<T>(method: 'GET' | 'POST' | 'DELETE', url: string, data?: unknown): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await api.request<T>({ method, url, ...(data === undefined ? {} : { data }) })
      return response.data
    } catch (error) {
      if (method !== 'GET' || attempt >= readRetryDelays.length || !isTransientReadError(error)) {
        throw error
      }
      await delay(readRetryDelays[attempt])
    }
  }
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

export function getPlatformStatus(): Promise<PlatformStatus> {
  return request<PlatformStatus>('GET', '/api/platform-status')
}
