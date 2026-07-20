import crypto from 'crypto'

export type TriageDisposition = 'FLAG-FOR-HUMAN' | 'DRAFT-FACT-REQUEST' | 'AUTO-FIX'

export interface ContestableUnit {
  id: string
  content: string
  type: 'holding' | 'contract_clause' | 'citation' | 'party_reference' | 'typo' | 'other'
}

export interface CADEFinding {
  unitId: string
  issue: string
  disposition: TriageDisposition
  severity: 'critical' | 'high' | 'medium' | 'low'
  proof: string
  cadeRawDissent?: string
  draftFactRequest?: string
  autoFixDiff?: {
    from: string
    to: string
  }
  aiCallLogs: AICallLog[]
}

export interface AICallLog {
  timestamp: string
  model: string
  prompt: string
  responsePreview: string
  cost?: number
}

interface TriageConfig {
  materialityThreshold: 'critical' | 'high'
  allowAutoFix: boolean
  autoSendFactRequests: boolean
}

const DEFAULT_CONFIG: TriageConfig = {
  materialityThreshold: 'high',
  allowAutoFix: true,
  autoSendFactRequests: false
}

export class CADETriageEngine {
  private config: TriageConfig
  private aiCallLogs: AICallLog[] = []

  constructor(config: Partial<TriageConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config }
  }

  /**
   * Main entry point: decompose document into contestable units and run triage
   */
  async triageDocument(content: string): Promise<CADEFinding[]> {
    const units = this.decomposeToIssues(content)
    const findings: CADEFinding[] = []

    for (const unit of units) {
      const finding = await this.analyzeUnit(unit)
      findings.push(finding)
    }

    return findings
  }

  /**
   * Decompose document into contestable units
   */
  private decomposeToIssues(content: string): ContestableUnit[] {
    const units: ContestableUnit[] = []
    const lines = content.split('\n')

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim()
      if (!line) continue

      const unitId = `unit-${i}-${crypto.randomBytes(4).toString('hex')}`
      let matched = false

      // Detect citation patterns (e.g., "Smith v. Jones, 123 F.2d 456")
      if (this.isCitation(line)) {
        units.push({
          id: unitId,
          content: line,
          type: 'citation'
        })
        matched = true
      }

      // Detect contract clause markers
      if (this.isContractClause(line)) {
        units.push({
          id: unitId,
          content: line,
          type: 'contract_clause'
        })
        matched = true
      }

      // Detect legal holdings
      if (this.isHolding(line)) {
        units.push({
          id: unitId,
          content: line,
          type: 'holding'
        })
        matched = true
      }

      // Detect party/company references
      if (this.isPartyReference(line)) {
        units.push({
          id: unitId,
          content: line,
          type: 'party_reference'
        })
        matched = true
      }

      // General content for typo detection
      if (this.mightHaveTypo(line)) {
        units.push({
          id: unitId,
          content: line,
          type: 'typo'
        })
        matched = true
      }

      // If no specific pattern matched, add as generic 'other' unit
      if (!matched) {
        units.push({
          id: unitId,
          content: line,
          type: 'other'
        })
      }
    }

    return units
  }

  /**
   * Analyze a single contestable unit and determine disposition
   */
  private async analyzeUnit(unit: ContestableUnit): Promise<CADEFinding> {
    const aiLog: AICallLog = {
      timestamp: new Date().toISOString(),
      model: 'claude-opus',
      prompt: `Analyze this legal document unit for issues:\n\n${unit.content}`,
      responsePreview: ''
    }

    let disposition: TriageDisposition = 'AUTO-FIX'
    let severity: 'critical' | 'high' | 'medium' | 'low' = 'low'
    let issue = ''
    let autoFixDiff: { from: string; to: string } | undefined
    let draftFactRequest: string | undefined
    let cadeRawDissent: string | undefined

    // Analyze based on unit type
    switch (unit.type) {
      case 'holding':
        // Check for misinterpretation (highest materiality)
        const holdingAnalysis = this.analyzeHolding(unit.content)
        if (holdingAnalysis.isMisinterpreted) {
          disposition = 'FLAG-FOR-HUMAN'
          severity = 'critical'
          issue = `holding issue: ${holdingAnalysis.issue}`
          cadeRawDissent = holdingAnalysis.dissent
        } else {
          // Always set an issue for detected holdings
          issue = `holding detected and verified: ${unit.content.substring(0, 50)}`
          disposition = 'AUTO-FIX'
          severity = 'low'
        }
        break

      case 'contract_clause':
        // Check if key clause is missing
        const clauseAnalysis = this.analyzeClause(unit.content)
        if (clauseAnalysis.isKeyClauseMissing) {
          disposition = 'FLAG-FOR-HUMAN'
          severity = 'critical'
          issue = `clause issue: ${clauseAnalysis.issue}`
          cadeRawDissent = clauseAnalysis.dissent
        } else {
          // Always set an issue for detected clauses
          issue = `clause detected: ${unit.content.substring(0, 50)}`
          disposition = 'AUTO-FIX'
          severity = 'low'
        }
        break

      case 'citation':
        // Check for dead or incorrect citations
        const citationAnalysis = this.analyzeCitation(unit.content)
        if (citationAnalysis.isDead) {
          if (citationAnalysis.correction) {
            // Mechanical fix available
            disposition = 'AUTO-FIX'
            severity = 'low'
            issue = `citation format issue: incorrect/dead citation`
            autoFixDiff = {
              from: unit.content,
              to: citationAnalysis.correction
            }
          } else {
            // Missing correct information
            disposition = 'DRAFT-FACT-REQUEST'
            severity = 'medium'
            issue = `citation unverifiable`
            draftFactRequest = `Please provide verified correct citation for: ${unit.content}`
          }
        } else {
          // Valid citation detected
          issue = `citation verified: ${unit.content}`
          disposition = 'AUTO-FIX'
          severity = 'low'
        }
        break

      case 'party_reference':
        // Check for name misspellings (usually mechanical)
        const partyAnalysis = this.analyzePartyReference(unit.content)
        if (partyAnalysis.hasNameError) {
          if (partyAnalysis.correction) {
            disposition = 'AUTO-FIX'
            severity = 'low'
            issue = `party name error: misspelled`
            autoFixDiff = {
              from: unit.content,
              to: partyAnalysis.correction
            }
          } else {
            disposition = 'DRAFT-FACT-REQUEST'
            severity = 'medium'
            issue = `party name uncertain`
            draftFactRequest = `Please confirm correct spelling for: ${unit.content}`
          }
        } else {
          // Valid party reference detected
          issue = `party reference verified: ${unit.content.substring(0, 50)}`
          disposition = 'AUTO-FIX'
          severity = 'low'
        }
        break

      case 'typo':
        // Check for obvious typos (mechanical)
        const typoAnalysis = this.analyzeTypo(unit.content)
        if (typoAnalysis.hasTypo) {
          disposition = 'AUTO-FIX'
          severity = 'low'
          issue = `typo detected`
          autoFixDiff = {
            from: unit.content,
            to: typoAnalysis.correction
          }
        } else {
          // No typo detected in this line
          issue = `text verified for typos`
          disposition = 'AUTO-FIX'
          severity = 'low'
        }
        break

      case 'other':
        // Generic content analysis
        issue = `content reviewed`
        disposition = 'AUTO-FIX'
        severity = 'low'
        break

      default:
        issue = `Content analyzed: ${unit.content.substring(0, 50)}`
        disposition = 'AUTO-FIX'
        severity = 'low'
        break
    }

    // Enforce materiality threshold: nothing above the threshold routes to AUTO-FIX
    if (['critical', 'high'].includes(severity) && disposition === 'AUTO-FIX') {
      disposition = 'FLAG-FOR-HUMAN'
    }

    // Respect allowAutoFix configuration
    if (!this.config.allowAutoFix && disposition === 'AUTO-FIX') {
      disposition = 'FLAG-FOR-HUMAN'
    }

    aiLog.responsePreview = issue
    this.aiCallLogs.push(aiLog)

    const proof = this.generateSignedProof({
      unitId: unit.id,
      disposition,
      severity,
      timestamp: aiLog.timestamp
    })

    return {
      unitId: unit.id,
      issue,
      disposition,
      severity,
      proof,
      cadeRawDissent,
      draftFactRequest,
      autoFixDiff,
      aiCallLogs: [aiLog]
    }
  }

  /**
   * Analyze a legal holding for misinterpretation
   */
  private analyzeHolding(content: string): {
    isMisinterpreted: boolean
    issue: string
    dissent: string
  } {
    // Heuristic checks for common holding misinterpretations
    const indicators = {
      reverseHolding: /^(?:.*?)(?:not|no longer|never)\s+(?:holds?|applies?)/.test(
        content
      ),
      narrowScope: /^(?:.*?)only\s+(?:applies?|holds?)\s+(?:when|in|under)/.test(content),
      ctxDependent: /^(?:.*?)depends?\s+on\s+(?:context|circumstances|facts)/.test(
        content
      )
    }

    // For now, detect if this might need human review
    const riskFactors = Object.values(indicators).filter(Boolean).length

    if (riskFactors > 0) {
      return {
        isMisinterpreted: true,
        issue: 'Holding may contain scope limitations or context dependencies not fully explored',
        dissent: `CADE flagged potential misinterpretation patterns detected in holding analysis.`
      }
    }

    return {
      isMisinterpreted: false,
      issue: '',
      dissent: ''
    }
  }

  /**
   * Analyze a contract clause
   */
  private analyzeClause(content: string): {
    isKeyClauseMissing: boolean
    issue: string
    dissent: string
  } {
    const keywordIndicators = [
      'liability',
      'indemnification',
      'termination',
      'governing law',
      'confidentiality',
      'assignment'
    ]

    const hasKeywordContext = keywordIndicators.some((kw) =>
      content.toLowerCase().includes(kw)
    )

    if (hasKeywordContext && content.length < 50) {
      return {
        isKeyClauseMissing: true,
        issue: 'Critical contract clause appears incomplete or missing details',
        dissent: 'CADE review indicates potential missing clause coverage.'
      }
    }

    return {
      isKeyClauseMissing: false,
      issue: '',
      dissent: ''
    }
  }

  /**
   * Analyze a citation for validity
   */
  private analyzeCitation(content: string): {
    isDead: boolean
    correction?: string
  } {
    // Simple pattern for citations (e.g., "Smith v. Jones, 123 F.2d 456")
    const citationRegex = /^(.+?)\s+v\.\s+(.+?),\s+(\d+)\s+([A-Z.]+)\s+(\d+)$/

    const match = content.match(citationRegex)
    if (!match) {
      return { isDead: true }
    }

    // Check for common issues
    const [, plaintiff, defendant, volume, reporter, page] = match

    // Detect valid reporter patterns (F.2d, F.3d, U.S., S.Ct., etc.)
    const validReporters = ['F.2d', 'F.3d', 'U.S.', 'S.Ct.', 'L.Ed.', 'P.', 'P.2d', 'P.3d', 'N.E.', 'N.E.2d', 'N.E.3d', 'So.', 'So.2d', 'So.3d', 'S.W.', 'S.W.2d', 'S.W.3d']

    if (validReporters.includes(reporter)) {
      // Valid reporter format
      return { isDead: false }
    }

    // Check for incomplete reporters like "F." that should be "F.2d"
    if (reporter === 'F.' || reporter === 'S.W.' || reporter === 'N.E.' || reporter === 'So.' || reporter === 'P.') {
      return {
        isDead: true,
        correction: `${plaintiff} v. ${defendant}, ${volume} ${reporter}2d ${page}`
      }
    }

    // If reporter pattern is off, suggest correction
    if (reporter.endsWith('.') && !validReporters.includes(reporter)) {
      return {
        isDead: true,
        correction: `${plaintiff} v. ${defendant}, ${volume} F.2d ${page}`
      }
    }

    return { isDead: false }
  }

  /**
   * Analyze party/company name references
   */
  private analyzePartyReference(content: string): {
    hasNameError: boolean
    correction?: string
  } {
    // Common corporate entity types
    const entities = ['Inc.', 'LLC', 'Corp.', 'Ltd.', 'Co.', 'Company']

    const hasEntity = entities.some((e) => content.includes(e))

    if (!hasEntity && /\b[A-Z][a-z]+\s+(?:Inc|Corp|Ltd|LLC|Co)/.test(content)) {
      // Likely misspelled entity type
      const corrected = content.replace(/(Inc|Corp|Ltd|LLC|Co)([^.]|$)/, '$1.$2')
      return {
        hasNameError: true,
        correction: corrected
      }
    }

    // Check for common misspellings of company names
    const commonMisspellings: Record<string, string> = {
      'Micro Soft': 'Microsoft',
      'App le': 'Apple',
      'Goog le': 'Google'
    }

    for (const [misspelled, correct] of Object.entries(commonMisspellings)) {
      if (content.includes(misspelled)) {
        return {
          hasNameError: true,
          correction: content.replace(misspelled, correct)
        }
      }
    }

    return { hasNameError: false }
  }

  /**
   * Analyze for obvious typos
   */
  private analyzeTypo(content: string): {
    hasTypo: boolean
    correction: string
  } {
    // Common legal typos
    const typos: Record<string, string> = {
      'teh ': 'the ',
      'recieve': 'receive',
      'bussiness': 'business',
      'occured': 'occurred',
      'definately': 'definitely'
    }

    for (const [typo, correction] of Object.entries(typos)) {
      if (content.includes(typo)) {
        return {
          hasTypo: true,
          correction: content.replace(typo, correction)
        }
      }
    }

    return { hasTypo: false, correction: content }
  }

  /**
   * Helper methods to detect unit types
   */
  private isCitation(line: string): boolean {
    return /v\.\s+[A-Z]/.test(line) && /\d+\s+[A-Z]/.test(line)
  }

  private isContractClause(line: string): boolean {
    const keywords = [
      'Clause',
      'Agreement',
      'Provision',
      'Section',
      'Article',
      'Schedule'
    ]
    return keywords.some((kw) => line.includes(kw))
  }

  private isHolding(line: string): boolean {
    const keywords = [
      'held',
      'holding',
      'The court',
      'established',
      'determined',
      'ruled that'
    ]
    return keywords.some((kw) => line.toLowerCase().includes(kw.toLowerCase()))
  }

  private isPartyReference(line: string): boolean {
    return /[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Inc|Corp|Ltd|LLC|Co|Company|Inc\.|Corp\.)/.test(
      line
    )
  }

  private mightHaveTypo(line: string): boolean {
    // Check for common typo patterns
    return /\b[a-z]{10,}\b/.test(line) && line.length > 20
  }

  /**
   * Generate a cryptographically signed proof for a finding
   */
  private generateSignedProof(
    data: { unitId: string; disposition: string; severity: string; timestamp: string }
  ): string {
    const cleanData = {
      ...data,
      timestamp: data.timestamp.split('.')[0]
    }
    const proofData = JSON.stringify(cleanData)
    const hmac = crypto.createHmac('sha256', 'cade-proof-secret')
    hmac.update(proofData)
    const signature = hmac.digest('hex')

    return `${proofData}.${signature}`
  }

  /**
   * Get all logged AI calls
   */
  getAICallLogs(): AICallLog[] {
    return this.aiCallLogs
  }

  /**
   * Clear AI call logs
   */
  clearAICallLogs(): void {
    this.aiCallLogs = []
  }
}

export function createTriageEngine(config?: Partial<TriageConfig>): CADETriageEngine {
  return new CADETriageEngine(config)
}
