import { describe, expect, it } from 'vitest'

import { deriveProofTimeline } from '~/utils/proofTimeline'

const base = {
  capability: 'Build',
  projectId: 'project-a',
  projectName: 'apparently',
}

describe('deriveProofTimeline', () => {
  it('binds evidence to the selected project instead of the first task and release', () => {
    const steps = deriveProofTimeline({
      ...base,
      tasks: [
        { slug: 'wrong', project_id: 'project-b', state: 'DEPLOYED_AND_VERIFIED', artifact_commit: 'wrongsha' },
        { slug: 'right', project_id: 'project-a', state: 'MERGED', artifact_commit: 'rightsha' },
      ],
      deployments: [
        { project: 'other', to_sha: 'rightsha', deploy_status: 'success' },
        { project: 'apparently', to_sha: 'wrongsha', deploy_status: 'success' },
      ],
    })

    expect(steps[0].detail).toBe('right')
    expect(steps.find(step => step.name === 'Integrated')?.done).toBe(true)
    expect(steps.find(step => step.name === 'Durable release')?.done).toBe(false)
  })

  it('never turns MERGED into independent verification or production proof', () => {
    const steps = deriveProofTimeline({
      ...base,
      tasks: [{ slug: 'merged', project_id: 'project-a', state: 'MERGED', artifact_commit: 'abc1234' }],
      deployments: [{ project: 'apparently', to_sha: 'abc1234', deploy_status: 'success' }],
    })

    expect(steps.find(step => step.name === 'Independently verified')?.done).toBe(false)
    expect(steps.find(step => step.name === 'Durable release')?.done).toBe(false)
  })

  it('requires canonical state plus an exact live release row', () => {
    const task = { slug: 'ship', project_id: 'project-a', state: 'DEPLOYED_AND_VERIFIED', artifact_commit: 'abc1234' }
    const missing = deriveProofTimeline({ ...base, tasks: [task], deployments: [] })
    const proven = deriveProofTimeline({
      ...base,
      tasks: [task],
      deployments: [{ id: 'release-1', project: 'apparently', to_sha: 'abc1234', deploy_status: 'success', vercel_url: 'https://app.example' }],
    })

    expect(missing.find(step => step.name === 'Durable release')?.done).toBe(false)
    expect(proven.find(step => step.name === 'Durable release')).toMatchObject({
      done: true,
      detail: 'https://app.example',
    })
  })
})
