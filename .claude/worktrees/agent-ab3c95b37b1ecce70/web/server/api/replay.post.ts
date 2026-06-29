// POST /api/replay  { run_id: string, project_id: string }
// Queues a replay task so the Mac runner re-executes a captured run snapshot.
import { createClient } from '@supabase/supabase-js'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { run_id, project_id } = body ?? {}
  if (!run_id || !project_id) {
    throw createError({ statusCode: 400, message: 'run_id and project_id required' })
  }

  const supabase = createClient(
    process.env.SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_KEY!
  )

  const { error } = await supabase.from('tasks').insert({
    project_id,
    slug: `replay-${run_id.slice(0, 8)}`,
    prompt: `REPLAY:${run_id}`,
    kind: 'replay',
    state: 'QUEUED',
  })

  if (error) throw createError({ statusCode: 500, message: error.message })
  return { ok: true }
})
