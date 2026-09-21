export interface TimelineTask {
  slug?: string | null
  state?: string | null
  kind?: string | null
  project_id?: string | null
  artifact_commit?: string | null
}

export interface TimelineDeployment {
  id?: string | null
  project?: string | null
  to_sha?: string | null
  deploy_status?: string | null
  vercel_url?: string | null
  note?: string | null
}

export interface TimelineStep {
  name: string
  detail: string
  done: boolean
  active: boolean
}

const LIVE_RELEASE_STATES = new Set(['success', 'deployed', 'ready', 'deployed_and_verified'])

function normalized(value: unknown): string {
  return String(value ?? '').trim().toLowerCase()
}

function matchingLiveDeployment(
  deployments: TimelineDeployment[],
  projectName: string | undefined,
  artifactCommit: string,
): TimelineDeployment | undefined {
  return (deployments ?? []).find((deployment) => {
    if (projectName && normalized(deployment.project) !== normalized(projectName)) return false
    return LIVE_RELEASE_STATES.has(normalized(deployment.deploy_status))
      && normalized(deployment.to_sha) === normalized(artifactCommit)
  })
}

/**
 * A proof timeline deliberately under-claims. A task state is a claim; the
 * artifact and exact release row are the evidence that allows the UI to render
 * the corresponding stage as proven.
 */
export function deriveProofTimeline({
  tasks,
  deployments = [],
  capability,
  projectId,
  projectName,
}: {
  tasks: TimelineTask[]
  deployments?: TimelineDeployment[]
  capability: string
  projectId?: string
  projectName?: string
}): TimelineStep[] {
  const task = (tasks ?? []).find(item => !projectId || item.project_id === projectId)
  const state = String(task?.state || '').toUpperCase()
  const artifactCommit = String(task?.artifact_commit || '').trim()
  const hasArtifact = artifactCommit.length > 0
  const integrated = hasArtifact && ['MERGED', 'DEPLOYED_AND_VERIFIED'].includes(state)
  const deployment = hasArtifact
    ? matchingLiveDeployment(deployments, projectName, artifactCommit)
    : undefined
  const deployedAndVerified = state === 'DEPLOYED_AND_VERIFIED' && Boolean(deployment)

  return [
    {
      name: 'Outcome understood',
      detail: task?.slug || `Ready for a ${capability} outcome`,
      done: Boolean(task),
      active: !task,
    },
    {
      name: 'Best route selected',
      detail: task?.kind ? `${task.kind} route · policy governed` : 'Selected automatically after intake',
      done: Boolean(task),
      active: state === 'QUEUED',
    },
    {
      name: 'Work executed',
      detail: hasArtifact ? `Artifact ${artifactCommit.slice(0, 12)}` : 'A recorded artifact commit is required',
      done: hasArtifact,
      active: ['RUNNING', 'VERIFYING'].includes(state),
    },
    {
      name: 'Independently verified',
      detail: deployedAndVerified ? 'Canonical production journey receipt accepted' : 'A linked verification receipt is still required',
      done: deployedAndVerified,
      active: hasArtifact && !deployedAndVerified,
    },
    {
      name: 'Integrated',
      detail: integrated
        ? 'Artifact recorded on the integration branch'
        : state === 'PHANTOM_UNVERIFIED'
          ? 'Merge claim lacks reachable artifact proof'
          : 'Not yet proven on the integration branch',
      done: integrated,
      active: hasArtifact && state === 'DONE',
    },
    {
      name: 'Durable release',
      detail: deployedAndVerified
        ? deployment?.vercel_url || deployment?.note || `Release ${deployment?.id || ''}`.trim()
        : integrated
          ? 'Merged is not deployed; exact-SHA production proof required'
          : 'Release train promotes verified work only',
      done: deployedAndVerified,
      active: integrated && !deployedAndVerified,
    },
  ]
}
