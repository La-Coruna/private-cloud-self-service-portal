export type ProjectStatus = 'REQUESTED' | 'PROVISIONING' | 'RUNNING' | 'FAILED' | 'DELETING' | 'DELETED'

export type Environment = 'dev' | 'staging' | 'prod'

export interface Project {
  id: number
  service_name: string
  environment: Environment
  image: string
  replicas: number
  cpu_request: string
  cpu_limit: string
  memory_request: string
  memory_limit: string
  expose_external: boolean
  namespace: string
  ingress_host: string | null
  status: ProjectStatus
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface ProjectCreatePayload {
  service_name: string
  environment: Environment
  image: string
  replicas: number
  cpu_request: string
  cpu_limit: string
  memory_request: string
  memory_limit: string
  expose_external: boolean
}

export interface ContainerStatus {
  name: string
  image: string
  ready: boolean
  restart_count: number
  state: string
  reason: string | null
  message: string | null
}

export interface PodStatus {
  name: string
  namespace: string
  phase: string
  pod_ip: string | null
  node_name: string | null
  start_time: string | null
  containers: ContainerStatus[]
}

export interface ProjectEvent {
  type: string | null
  reason: string | null
  message: string | null
  count: number | null
  involved_object_kind: string | null
  involved_object_name: string | null
  first_timestamp: string | null
  last_timestamp: string | null
  event_time: string | null
  source_component: string | null
}

export interface AuditLog {
  id: number
  project_id: number
  action: string
  status: string
  message: string | null
  created_at: string
}