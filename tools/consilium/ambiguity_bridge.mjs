// ambiguity_bridge.mjs — run apparently-law's deterministic guidance-ambiguity miner over text
// piped in as JSON ({text, definedTerms?, sourceRef?}) and print ranked findings as JSON.
//
// The miner (contracts/guidance-ambiguity.js) is pure and dependency-free; it scores OBSERVABLE
// textual features (undefined terms, vague qualifiers, discretionary modals, unbounded
// deadlines, conflicting cross-references) and refuses any finding it cannot quote. We call it
// from Python rather than porting it so the firm's engine and the Consilium's cannot drift.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import path from 'node:path'

const dir = process.env.APPARENTLY_LAW_DIR || path.join(process.env.HOME || '', 'Documents', 'apparently-law')
const mod = await import(pathToFileURL(path.join(dir, 'contracts', 'guidance-ambiguity.js')).href)
const input = JSON.parse(readFileSync(0, 'utf8'))
const mined = mod.mineAmbiguity(input.text || '', { definedTerms: input.definedTerms || [], sourceRef: input.sourceRef || null })
const top = mined.ok ? mod.rankFindings(mined.findings, { limit: input.limit || 15 }) : []
process.stdout.write(JSON.stringify({ ok: mined.ok, reason: mined.reason || null, score: mined.score || 0,
  total: mined.ok ? mined.findings.length : 0, findings: Array.isArray(top) ? top : (top?.findings || []) }))
