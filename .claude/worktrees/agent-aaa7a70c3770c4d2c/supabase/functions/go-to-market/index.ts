// POST { slug, target_project, product_name }
// Instantiates a productizable capability in a target app and queues a GTM build task.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  )

  const { slug, target_project, product_name } = await req.json()
  if (!slug || !target_project || !product_name) {
    return new Response(JSON.stringify({ error: 'slug, target_project, product_name required' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } })
  }

  const { data: cap, error: capErr } = await supabase
    .from('capabilities').select('*').eq('slug', slug).single()
  if (capErr || !cap) {
    return new Response(JSON.stringify({ error: 'capability not found' }),
      { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } })
  }
  if (cap.status !== 'productizable') {
    return new Response(JSON.stringify({ error: `capability not productizable (status=${cap.status})` }),
      { status: 409, headers: { ...corsHeaders, 'Content-Type': 'application/json' } })
  }

  const { data: proj } = await supabase
    .from('projects').select('id').eq('name', target_project).single()
  if (!proj) {
    return new Response(JSON.stringify({ error: 'target project not registered' }),
      { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } })
  }

  // check provenance consent
  const { data: provRows } = await supabase
    .from('capability_provenance').select('consent').eq('capability_id', cap.id)
  const consented = provRows?.length && provRows.every((r: any) => r.consent)
  if (!consented) {
    return new Response(JSON.stringify({ error: 'consent not granted for this capability' }),
      { status: 403, headers: { ...corsHeaders, 'Content-Type': 'application/json' } })
  }

  // get latest version
  const { data: vers } = await supabase
    .from('capability_versions').select('semver')
    .eq('capability_id', cap.id).order('created_at', { ascending: false }).limit(1)
  const semver = vers?.[0]?.semver ?? '0.1.0'

  // instantiate
  await supabase.from('capability_instances').insert({
    capability_id: cap.id, project: target_project, version: semver, status: 'active',
  })

  // queue GTM build task
  const prompt = `Productize the '${cap.name}' capability as a new offering named '${product_name}' in this app. ` +
    `Scaffold, behind a feature flag (default OFF): (1) a landing/marketing page, (2) a pricing component (stub tiers), ` +
    `(3) user docs, (4) an onboarding flow that invokes the capability. ` +
    `Capability summary: ${cap.summary}. Contract: ${JSON.stringify(cap.contract)}. ` +
    `Add tests for both flag states; do NOT enable the flag. Keep the build green.`

  await supabase.from('tasks').insert({
    project_id: proj.id, slug: `gtm-${slug}`, kind: 'build',
    state: 'QUEUED', prompt, capability_slug: slug,
  })

  return new Response(JSON.stringify({ ok: true, queued: `gtm-${slug}`, project: target_project }),
    { headers: { ...corsHeaders, 'Content-Type': 'application/json' } })
})
