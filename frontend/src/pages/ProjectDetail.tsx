import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { QueryState } from '../components/QueryState'
import { StatusBadge } from '../components/StatusBadge'
import { deleteProject, getAuditLogs, getEvents, getPods, getProject, syncProjectStatus } from '../lib/api'
import { formatDateTime, textOrDash } from '../lib/format'

export function ProjectDetailPage() {
  const { id } = useParams()
  const projectId = Number(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const projectQuery = useQuery({ queryKey: ['project', projectId], queryFn: () => getProject(projectId), enabled: Number.isFinite(projectId) })
  const podsQuery = useQuery({ queryKey: ['project', projectId, 'pods'], queryFn: () => getPods(projectId), enabled: Number.isFinite(projectId) })
  const eventsQuery = useQuery({ queryKey: ['project', projectId, 'events'], queryFn: () => getEvents(projectId), enabled: Number.isFinite(projectId) })
  const auditsQuery = useQuery({ queryKey: ['project', projectId, 'audit-logs'], queryFn: () => getAuditLogs(projectId), enabled: Number.isFinite(projectId) })

  const syncMutation = useMutation({
    mutationFn: () => syncProjectStatus(projectId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['project', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project', projectId, 'pods'] }),
        queryClient.invalidateQueries({ queryKey: ['project', projectId, 'events'] }),
        queryClient.invalidateQueries({ queryKey: ['project', projectId, 'audit-logs'] }),
      ])
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(projectId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      await queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      navigate('/projects')
    },
  })

  function confirmDelete() {
    if (window.confirm('Delete this project and its Kubernetes resources?')) {
      deleteMutation.mutate()
    }
  }

  return (
    <section className="page-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Project detail</p>
          <h1>{projectQuery.data?.service_name ?? 'Project detail'}</h1>
        </div>
        <div className="action-row">
          <Link className="secondary-action" to="/projects">Back to list</Link>
          <button className="secondary-action" type="button" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending || deleteMutation.isPending}>
            {syncMutation.isPending ? 'Refreshing' : 'Refresh status'}
          </button>
          <button className="danger-action" type="button" onClick={confirmDelete} disabled={deleteMutation.isPending || syncMutation.isPending}>
            Delete
          </button>
        </div>
      </div>

      <QueryState isLoading={projectQuery.isLoading} isError={projectQuery.isError} error={projectQuery.error}>
        {projectQuery.data && (
          <>
            <div className="summary-grid">
              <div><span>Status</span><strong><StatusBadge status={projectQuery.data.status} /></strong></div>
              <div><span>Namespace</span><strong className="mono">{projectQuery.data.namespace}</strong></div>
              <div><span>Image</span><strong className="mono">{projectQuery.data.image}</strong></div>
              <div><span>Ingress</span><strong className="mono">{textOrDash(projectQuery.data.ingress_host)}</strong></div>
              <div><span>Replicas</span><strong>{projectQuery.data.replicas}</strong></div>
              <div><span>Resources</span><strong>{projectQuery.data.cpu_request}/{projectQuery.data.cpu_limit}, {projectQuery.data.memory_request}/{projectQuery.data.memory_limit}</strong></div>
            </div>
            {projectQuery.data.error_message && <div className="notice error">{projectQuery.data.error_message}</div>}
          </>
        )}
      </QueryState>

      <div className="detail-grid">
        <section className="data-panel">
          <h2>Pod status</h2>
          <QueryState isLoading={podsQuery.isLoading} isError={podsQuery.isError} error={podsQuery.error}>
            {(podsQuery.data ?? []).length === 0 ? <div className="notice">No Pod data.</div> : (
              <div className="table-wrap compact"><table><thead><tr><th>name</th><th>phase</th><th>node</th><th>containers</th></tr></thead><tbody>
                {(podsQuery.data ?? []).map((pod) => <tr key={pod.name}><td className="mono">{pod.name}</td><td>{pod.phase}</td><td>{textOrDash(pod.node_name)}</td><td>{pod.containers.map((container) => `${container.name}:${container.state}${container.reason ? `(${container.reason})` : ''}`).join(', ')}</td></tr>)}
              </tbody></table></div>
            )}
          </QueryState>
        </section>

        <section className="data-panel">
          <h2>Kubernetes Event</h2>
          <QueryState isLoading={eventsQuery.isLoading} isError={eventsQuery.isError} error={eventsQuery.error}>
            {(eventsQuery.data ?? []).length === 0 ? <div className="notice">No Event data.</div> : (
              <div className="table-wrap compact"><table><thead><tr><th>reason</th><th>object</th><th>message</th><th>time</th></tr></thead><tbody>
                {(eventsQuery.data ?? []).map((event, index) => <tr key={`${event.reason}-${index}`}><td>{textOrDash(event.reason)}</td><td className="mono">{textOrDash(event.involved_object_name)}</td><td>{textOrDash(event.message)}</td><td>{formatDateTime(event.last_timestamp ?? event.event_time ?? event.first_timestamp)}</td></tr>)}
              </tbody></table></div>
            )}
          </QueryState>
        </section>
      </div>

      <section className="data-panel full-width">
        <h2>Audit Log</h2>
        <QueryState isLoading={auditsQuery.isLoading} isError={auditsQuery.isError} error={auditsQuery.error}>
          {(auditsQuery.data ?? []).length === 0 ? <div className="notice">No Audit Log data.</div> : (
            <div className="timeline">
              {(auditsQuery.data ?? []).map((log) => <div className="timeline-row" key={log.id}><time>{formatDateTime(log.created_at)}</time><strong>{log.action}</strong><span>{log.status}</span><p>{textOrDash(log.message)}</p></div>)}
            </div>
          )}
        </QueryState>
      </section>
    </section>
  )
}
