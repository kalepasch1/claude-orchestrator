// POST /api/go-to-market  { slug, target_project, product_name }
// Thin server-side proxy to the go-to-market Supabase edge function.
import { createClient } from '@supabase/supabase-js'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { slug, target_project, product_name } = body ?? {}
  if (!slug || !target_project || !product_name) {
    throw createError({ statusCode: 400, message: 'slug, target_project, product_name required' })
  }

  const supabase = createClient(
    process.env.SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_KEY!,
  )

  const { data, error } = await supabase.functions.invoke('go-to-market', {
    body: { slug, target_project, product_name },
  })

  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
})
