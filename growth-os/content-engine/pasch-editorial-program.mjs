#!/usr/bin/env node
/**
 * Review-first editorial planner for kale-pasch and the product portfolio.
 * It creates research/drafting tasks and approval records only. It never
 * publishes, submits a speaking application, sends an email, or uses private
 * matter material.
 */
import { createClient } from '@supabase/supabase-js'

const orch = createClient(process.env.ORCH_SUPABASE_URL, process.env.ORCH_SUPABASE_SERVICE_KEY)
const app = process.env.APP_NAME || 'kale-pasch'
const limit = Number(process.env.LIMIT || 3)

const cadePanel = [
  'financial-regulation and derivatives authority',
  'digital-assets and FinTech authority',
  'gaming and interactive-products authority',
  'product and governance operator',
  'legal-editor and ethics reviewer',
  'adversarial fact-and-citation verifier',
]

async function dueItems() {
  const { data, error } = await orch.from('growth_content_calendar')
    .select('id, app, platform, kind, topic_hint, cadence, meta')
    .eq('app', app).eq('active', true).lte('next_due', new Date().toISOString())
    .order('next_due').limit(limit)
  if (error) throw new Error(error.message)
  return data || []
}

async function seed(item) {
  const title = `${item.app} · ${item.topic_hint}`
  const prompt = [
    `Prepare a review-ready ${item.kind} for ${item.app}: ${item.topic_hint}.`,
    `CADE panel: ${cadePanel.join('; ')}.`,
    'Use only primary authorities, authorized public materials, and a documented source map.',
    'Never include client names, employer-confidential material, non-public matter details, or unsupported claims.',
    'Deliver: optimized outline; reader decision; source plan; fact/inference/open-question split; preserved dissent; full draft; channel derivatives; publication-risk checklist.',
    'File a human approval after drafting. Do not publish, send, submit, or contact anyone externally.',
  ].join('\n')
  const slug = `editorial-${item.app}-${item.id}`
  const { error } = await orch.from('tasks').insert({ project: item.app, slug, prompt, kind: 'gtm', state: 'QUEUED', note: `review-first editorial planner · ${item.platform}/${item.cadence}` })
  if (error) throw new Error(error.message)
  return { slug, title }
}

const items = await dueItems()
const seeded = []
for (const item of items) seeded.push(await seed(item))
console.table(seeded)
