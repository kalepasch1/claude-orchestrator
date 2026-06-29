/**
 * Policy-as-a-product (new improvement #2) — a clean facade that bundles
 * compile → govern → export → verify into a sellable compliance service. The
 * deliverable a regulated buyer wants is: "author policy in English, and prove my
 * agents stayed inside it." This packages exactly that on top of the kernel.
 *
 *   - `PolicyService.fromText(...)` compiles NL policy into an enforced constitution.
 *   - `.govern(action)` evaluates + mints a chained receipt (maintains the chain).
 *   - `.exportPack()` produces a CompliancePack: the constitution + the full signed
 *      receipt chain. This is the artifact you hand an auditor/regulator/customer.
 *   - `verifyCompliancePack(pack)` is STATELESS — anyone validates it offline with
 *      no DB and no secret. That third-party verifiability is the product.
 */
import type { AgentAction, ProductId } from '../types.ts';
import { compileConstitution } from './compiler.ts';
import type { Constitution } from './constitution.ts';
import { governAction } from './index.ts';
import { verifyChain, type Receipt } from './receipts.ts';
import { sha256Canonical } from '../crypto/hash.ts';

export interface CompliancePack {
  product: ProductId;
  constitution: Constitution;
  receipts: Receipt[];
  /** digest over {constitution, receipts} — pins the pack contents */
  digest: string;
}

export interface PackVerification {
  valid: boolean;
  reason: string;
  chainOk: boolean;
  receiptCount: number;
}

export class PolicyService {
  private constitution: Constitution;
  private readonly product: ProductId;
  private chain: Receipt[] = [];

  constructor(product: ProductId, constitution: Constitution) {
    this.product = product;
    this.constitution = constitution;
  }

  /** Build a service straight from plain-English policy text. */
  static fromText(params: {
    product: ProductId;
    text: string;
    alwaysEscalate?: string[];
    lockedDimensions?: string[];
    version?: number;
  }): PolicyService {
    const { constitution } = compileConstitution(params);
    return new PolicyService(params.product, constitution);
  }

  getConstitution(): Constitution {
    return this.constitution;
  }

  /** Evaluate an action and append a signed, hash-linked receipt to the chain. */
  govern(action: AgentAction): { decision: Receipt['decision']; receipt: Receipt } {
    const prev = this.chain[this.chain.length - 1] ?? null;
    const { verdict, receipt } = governAction({
      action,
      constitution: this.constitution,
      prevReceipt: prev,
      chain: `${this.product}:policy`,
    });
    this.chain.push(receipt);
    return { decision: verdict.decision, receipt };
  }

  /** The sellable artifact: constitution + full signed receipt chain. */
  exportPack(): CompliancePack {
    const body = { constitution: this.constitution, receipts: this.chain };
    return { product: this.product, ...body, digest: sha256Canonical(body) };
  }
}

/** Stateless, offline verification of a compliance pack (the product's proof). */
export function verifyCompliancePack(pack: CompliancePack): PackVerification {
  const recomputed = sha256Canonical({ constitution: pack.constitution, receipts: pack.receipts });
  if (recomputed !== pack.digest) {
    return { valid: false, reason: 'pack_digest_mismatch', chainOk: false, receiptCount: pack.receipts.length };
  }
  const chain = verifyChain(pack.receipts);
  return {
    valid: chain.ok,
    reason: chain.ok ? 'ok' : `chain_broken_at_${chain.brokenAt}`,
    chainOk: chain.ok,
    receiptCount: pack.receipts.length,
  };
}
