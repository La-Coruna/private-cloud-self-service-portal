import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { StatusBadge } from '../components/StatusBadge'
import { QueryState } from '../components/QueryState'
import { getProjects } from '../lib/api'
import { formatDateTime, textOrDash } from '../lib/format'

export function ProjectListPage() {
  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: getProjects })
  const projects = projectsQuery.data ?? []

  return (
    <section className="page-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Projects</p>
          <h1>프로젝트 목록</h1>
        </div>
        <Link className="primary-action" to="/projects/new">새 프로젝트</Link>
      </div>

      <QueryState isLoading={projectsQuery.isLoading} isError={projectsQuery.isError} error={projectsQuery.error}>
        {projects.length === 0 ? (
          <div className="notice">아직 생성된 프로젝트가 없습니다.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>service</th>
                  <th>env</th>
                  <th>image</th>
                  <th>namespace</th>
                  <th>status</th>
                  <th>external</th>
                  <th>ingress</th>
                  <th>created</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((project) => (
                  <tr key={project.id}>
                    <td><Link className="row-link" to={`/projects/${project.id}`}>{project.service_name}</Link></td>
                    <td>{project.environment}</td>
                    <td className="mono">{project.image}</td>
                    <td className="mono">{project.namespace}</td>
                    <td><StatusBadge status={project.status} /></td>
                    <td>{project.expose_external ? 'yes' : 'no'}</td>
                    <td className="mono">{textOrDash(project.ingress_host)}</td>
                    <td>{formatDateTime(project.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
    </section>
  )
}