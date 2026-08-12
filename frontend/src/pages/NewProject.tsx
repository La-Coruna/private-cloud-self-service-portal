import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { FormEvent } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ErrorCard } from '../components/ErrorCard'
import { createProject } from '../lib/api'
import { normalizeApiError } from '../lib/error'
import type { Environment, ProjectCreatePayload } from '../lib/types'

const initialForm: ProjectCreatePayload = {
  service_name: '',
  environment: 'staging',
  image: 'nginx:latest',
  replicas: 1,
  cpu_request: '100m',
  cpu_limit: '500m',
  memory_request: '128Mi',
  memory_limit: '512Mi',
  expose_external: false,
}

const rulesPanelId = 'demo-rules-panel'

interface NewProjectPageProps {
  creationAllowed: boolean
}

export function NewProjectPage({ creationAllowed }: NewProjectPageProps) {
  const [form, setForm] = useState<ProjectCreatePayload>(initialForm)
  const [rulesOpen, setRulesOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: createProject,
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${project.id}`)
    },
  })
  const normalizedError = mutation.error ? normalizeApiError(mutation.error) : null

  function update<K extends keyof ProjectCreatePayload>(key: K, value: ProjectCreatePayload[K]) {
    if (mutation.isError) mutation.reset()
    setForm((current) => ({ ...current, [key]: value }))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    mutation.mutate(form)
  }

  return (
    <section className="page-section narrow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Request</p>
          <h1>{'\ud504\ub85c\uc81d\ud2b8 \uc0dd\uc131'}</h1>
        </div>
        <button
          aria-controls={rulesPanelId}
          aria-expanded={rulesOpen}
          className="secondary-action help-button"
          type="button"
          onClick={() => setRulesOpen((current) => !current)}
        >
          {rulesOpen ? '\uc785\ub825 \uaddc\uce59 \ub2eb\uae30' : '\uc785\ub825 \uaddc\uce59 \ubcf4\uae30'}
        </button>
      </div>

      {rulesOpen && (
        <aside className="demo-rules-panel" id={rulesPanelId}>
          <strong>{'\uacf5\uac1c \ub370\ubaa8 \uc785\ub825 \uaddc\uce59'}</strong>
          <ul>
            <li>{'GCP \ube44\uc6a9\uacfc \ud074\ub7ec\uc2a4\ud130 \uc790\uc6d0\uc744 \ubcf4\ud638\ud558\uae30 \uc704\ud574 \uc77c\ubd80 \uc785\ub825\uac12\uc744 \uc81c\ud55c\ud569\ub2c8\ub2e4.'}</li>
            <li>{'Replica \uc218\ub294 1\uac1c\ub9cc \ud5c8\uc6a9\ud569\ub2c8\ub2e4.'}</li>
            <li>{'\ud5c8\uc6a9 \uc774\ubbf8\uc9c0: nginx:latest, httpd:alpine, nginx-not-exist-demo:latest'}</li>
            <li>{'Service name\uc740 demo-, portfolio-, broken- prefix\ub97c \uc0ac\uc6a9\ud574 \uc8fc\uc138\uc694.'}</li>
            <li>{'\uc678\ubd80 \uacf5\uac1c\ub97c \uc120\ud0dd\ud558\uba74 {service_name}-{environment}.apps.la-coruna.xyz \uc8fc\uc18c\uac00 \uc0dd\uc131\ub429\ub2c8\ub2e4.'}</li>
            <li>{'\ud604\uc7ac \ub370\ubaa8\ub294 HTTP\ub9cc \uc9c0\uc6d0\ud569\ub2c8\ub2e4.'}</li>
            <li>{'\uc0dd\uc131 \uc2e4\ud328 \uc2dc \uc544\ub798 \uc624\ub958 \uba54\uc2dc\uc9c0\uc5d0\uc11c \uc81c\ud55c \uc704\ubc18 \uc0ac\uc720\ub97c \ud655\uc778\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.'}</li>
          </ul>
        </aside>
      )}

      <form className="form-grid" onSubmit={submit}>
        <label>
          Service name
          <input required value={form.service_name} onChange={(event) => update('service_name', event.target.value)} placeholder="demo-api" />
          <span className="field-hint">{'\ud5c8\uc6a9 prefix: demo-, portfolio-, broken-'}</span>
        </label>
        <label>
          Environment
          <select value={form.environment} onChange={(event) => update('environment', event.target.value as Environment)}>
            <option value="dev">dev</option>
            <option value="staging">staging</option>
            <option value="prod">prod</option>
          </select>
        </label>
        <label className="span-2">
          Image
          <input required value={form.image} onChange={(event) => update('image', event.target.value)} />
          <span className="field-hint">{'\ud5c8\uc6a9 \uc774\ubbf8\uc9c0: nginx:latest, httpd:alpine, nginx-not-exist-demo:latest'}</span>
        </label>
        <label>
          Replicas
          <input type="number" min="1" max="5" value={form.replicas} onChange={(event) => update('replicas', Number(event.target.value))} />
          <span className="field-hint">{'\uacf5\uac1c \ub370\ubaa8\uc5d0\uc11c\ub294 1\ub85c \uc81c\ud55c\ub429\ub2c8\ub2e4.'}</span>
        </label>
        <label>
          CPU request
          <input value={form.cpu_request} onChange={(event) => update('cpu_request', event.target.value)} />
        </label>
        <label>
          CPU limit
          <input value={form.cpu_limit} onChange={(event) => update('cpu_limit', event.target.value)} />
        </label>
        <label>
          Memory request
          <input value={form.memory_request} onChange={(event) => update('memory_request', event.target.value)} />
        </label>
        <label>
          Memory limit
          <input value={form.memory_limit} onChange={(event) => update('memory_limit', event.target.value)} />
        </label>
        <label className="check-row span-2">
          <input type="checkbox" checked={form.expose_external} onChange={(event) => update('expose_external', event.target.checked)} />
          <span>
            {'\uc678\ubd80 \uc811\uc18d Ingress \uc0dd\uc131'}
            <small className="field-hint">{'\uc120\ud0dd \uc2dc *.apps.la-coruna.xyz \uc8fc\uc18c\uac00 \uc0dd\uc131\ub429\ub2c8\ub2e4.'}</small>
          </span>
        </label>
        {normalizedError && <div className="span-2"><ErrorCard error={normalizedError} /></div>}
        <div className="form-actions span-2">
          <button className="primary-action" type="submit" disabled={!creationAllowed || mutation.isPending}>
            {mutation.isPending ? '\uc0dd\uc131 \uc911' : '\uc0dd\uc131'}
          </button>
        </div>
      </form>
    </section>
  )
}
