import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { FormEvent } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { createProject } from '../lib/api'
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

export function NewProjectPage() {
  const [form, setForm] = useState<ProjectCreatePayload>(initialForm)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: createProject,
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${project.id}`)
    },
  })

  function update<K extends keyof ProjectCreatePayload>(key: K, value: ProjectCreatePayload[K]) {
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
          <h1>프로젝트 생성</h1>
        </div>
      </div>

      <form className="form-grid" onSubmit={submit}>
        <label>
          Service name
          <input required value={form.service_name} onChange={(event) => update('service_name', event.target.value)} placeholder="demo-api" />
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
        </label>
        <label>
          Replicas
          <input type="number" min="1" max="5" value={form.replicas} onChange={(event) => update('replicas', Number(event.target.value))} />
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
          외부 접속 Ingress 생성
        </label>
        {mutation.isError && <div className="notice error span-2">프로젝트 생성에 실패했습니다.</div>}
        <div className="form-actions span-2">
          <button className="primary-action" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? '생성 중' : '생성'}
          </button>
        </div>
      </form>
    </section>
  )
}