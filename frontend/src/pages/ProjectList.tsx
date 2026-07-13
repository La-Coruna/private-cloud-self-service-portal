import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { QueryState } from '../components/QueryState'
import { StatusBadge } from '../components/StatusBadge'
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
          <h1>{'\ud504\ub85c\uc81d\ud2b8 \ubaa9\ub85d'}</h1>
        </div>
        <Link className="primary-action" to="/projects/new">{'\uc0c8 \ud504\ub85c\uc81d\ud2b8'}</Link>
      </div>

      <QueryState isLoading={projectsQuery.isLoading} isError={projectsQuery.isError} error={projectsQuery.error}>
        {projects.length === 0 ? (
          <div className="notice">{'\uc544\uc9c1 \uc0dd\uc131\ub41c \ud504\ub85c\uc81d\ud2b8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.'}</div>
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
