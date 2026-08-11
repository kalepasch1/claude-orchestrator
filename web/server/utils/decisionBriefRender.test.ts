/**
 * render-decision-briefs — recovery test.
 *
 * THE STALL
 * ---------
 * `legal_prebrief.py` writes a plain-English brief into `approvals.prebrief`;
 * `owner_decision_model.py` writes `options`, `recommended_index` /
 * `suggested_option_index`, and `model_rationale` into `approvals.brief_json`.
 * The review UI never read either field — `deriveDecisionBrief` classified from
 * `kind`/`title`/`why` keywords alone — so all of that orchestrator work was
 * written to the database and then silently discarded at render time.
 *
 * These tests simulate the exact rows the orchestrator produces and assert that
 * (a) the derived brief carries the content and (b) the real `DecisionBrief.vue`
 * component renders it. The component is rendered with `vue/server-renderer`,
 * which needs no DOM and no extra dependency.
 */

import { describe, expect, it } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import DecisionBrief from '../../components/DecisionBrief.vue'
import { deriveDecisionBrief } from '../../utils/decisionBrief'

/** Verbatim shape of what legal_prebrief.py stores. */
const PREBRIEF =
  'You are deciding whether to sign the reseller addendum. The risk is an ' +
  'uncapped indemnity clause. Most founders cap indemnity at fees paid in the ' +
  'prior 12 months. Recommend negotiating the cap before signing; counsel is ' +
  'worth it here. Not legal advice — consult counsel for anything binding.'

/** Verbatim shape of what owner_decision_model.py stores in brief_json. */
function orchestratorRow(overrides: Record<string, any> = {}) {
  return {
    id: 'apr-1',
    kind: 'legal',
    title: 'Reseller addendum sign-off',
    why: 'Partner requires a signed addendum before launch.',
    project: 'apparently',
    prebrief: PREBRIEF,
    brief_json: {
      options: [
        { label: 'Sign as drafted', detail: 'Fastest path; accepts uncapped indemnity.' },
        { label: 'Negotiate an indemnity cap', detail: 'Cap at fees paid in the prior 12 months.' },
        { label: 'Decline and escalate to counsel' },
      ],
      suggested_option_index: 1,
      recommended_index: 1,
      model_rationale: 'owner-decision-model: 7 precedents in category ‘legal’; owner has consistently capped indemnity.',
    },
    ...overrides,
  }
}

async function render(approval: Record<string, any>, compact = false): Promise<string> {
  return renderToString(createSSRApp(DecisionBrief, { approval, compact }))
}

describe('deriveDecisionBrief reads the orchestrator fields', () => {
  it('uses approvals.prebrief as the plain-language summary', () => {
    const brief = deriveDecisionBrief(orchestratorRow())
    expect(brief.prebrief).toBe(PREBRIEF)
    expect(brief.plainLanguage).toBe(PREBRIEF)
    expect(brief.source).toBe('orchestrator')
  })

  it('surfaces the options from brief_json', () => {
    const brief = deriveDecisionBrief(orchestratorRow())
    expect(brief.options.map(o => o.label)).toEqual([
      'Sign as drafted',
      'Negotiate an indemnity cap',
      'Decline and escalate to counsel',
    ])
  })

  it('marks the recommended option and carries the model rationale', () => {
    const brief = deriveDecisionBrief(orchestratorRow())
    expect(brief.recommendedIndex).toBe(1)
    expect(brief.options[1].recommended).toBe(true)
    expect(brief.options[0].recommended).toBe(false)
    expect(brief.modelRationale).toContain('owner-decision-model')
  })

  it('accepts brief_json delivered as a JSON string', () => {
    const row = orchestratorRow()
    const brief = deriveDecisionBrief({ ...row, brief_json: JSON.stringify(row.brief_json) })
    expect(brief.options).toHaveLength(3)
    expect(brief.recommendedIndex).toBe(1)
  })

  it('falls back to suggested_option_index when recommended_index is absent', () => {
    const row = orchestratorRow()
    delete (row.brief_json as any).recommended_index
    expect(deriveDecisionBrief(row).recommendedIndex).toBe(1)
  })

  it('honours an explicit recommendation and confidence from brief_json', () => {
    const row = orchestratorRow()
    Object.assign(row.brief_json as any, { recommendation: 'ESCALATE', confidence: 0.42 })
    const brief = deriveDecisionBrief(row)
    expect(brief.recommendation).toBe('ESCALATE')
    expect(brief.confidence).toBe(42) // 0–1 confidences are scaled to percent
  })
})

describe('deriveDecisionBrief degrades safely', () => {
  it('ignores malformed brief_json rather than blanking the card', () => {
    const brief = deriveDecisionBrief({ kind: 'legal', title: 'Counsel sign-off', brief_json: '{not json' })
    expect(brief.options).toEqual([])
    expect(brief.classification).toContain('Legal')
  })

  it('drops an out-of-range recommended_index', () => {
    const row = orchestratorRow()
    ;(row.brief_json as any).recommended_index = 9
    ;(row.brief_json as any).suggested_option_index = 9
    expect(deriveDecisionBrief(row).recommendedIndex).toBeUndefined()
  })

  it('leaves a card with neither field on the heuristic path', () => {
    const brief = deriveDecisionBrief({ kind: 'secret', title: 'Set API token' })
    expect(brief.source).toBe('derived')
    expect(brief.options).toEqual([])
    expect(brief.material).toBe(true)
  })
})

describe('DecisionBrief.vue renders the orchestrator brief', () => {
  it('renders the prebrief text in the plain-language slot', async () => {
    const html = await render(orchestratorRow())
    expect(html).toContain('uncapped indemnity clause')
    expect(html).toContain('Not legal advice')
  })

  it('renders every option label', async () => {
    const html = await render(orchestratorRow())
    expect(html).toContain('Sign as drafted')
    expect(html).toContain('Negotiate an indemnity cap')
    expect(html).toContain('Decline and escalate to counsel')
  })

  it('marks the recommended option and shows the rationale', async () => {
    const html = await render(orchestratorRow())
    expect(html).toContain('data-testid="brief-recommended-option"')
    expect(html).toContain('data-testid="brief-model-rationale"')
    expect(html).toContain('owner-decision-model')
  })

  it('labels the brief as orchestrator-sourced', async () => {
    const html = await render(orchestratorRow())
    expect(html).toContain('Orchestrator brief')
  })

  it('still renders the options block in compact mode', async () => {
    const html = await render(orchestratorRow(), true)
    expect(html).toContain('data-testid="brief-options"')
    expect(html).toContain('Negotiate an indemnity cap')
  })

  it('renders no options block and no orchestrator badge for a plain card', async () => {
    const html = await render({ kind: 'secret', title: 'Set API token' })
    expect(html).not.toContain('data-testid="brief-options"')
    expect(html).not.toContain('Orchestrator brief')
    // The heuristic brief must still render.
    expect(html).toContain('Credential')
  })
})
