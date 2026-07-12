import { getPlaybooks, getExecutionHistory } from '~/server/utils/autoRemediation'

export default defineEventHandler(async () => {
  try {
    const playbooks = getPlaybooks()
    const executions = getExecutionHistory()
    return { playbooks, executions }
  } catch (e: any) {
    throw createError({ statusCode: 500, message: e.message || 'Failed to fetch playbooks' })
  }
})
