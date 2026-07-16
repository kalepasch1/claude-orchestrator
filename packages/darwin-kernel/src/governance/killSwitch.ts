/**
 * Portfolio kill switch — a single control surface that flips the constitution
 * `killSwitch` for ALL registered products at once via the shared darwin_*
 * tables. Fail-closed: if the switch is engaged, every `evaluateConstitution`
 * call short-circuits to deny.
 *
 * Each flip generates a receipt per product proving exactly what each bot did
 * (or was prevented from doing).
 */
import type { ProductId, AgentAction } from '../types.ts';
import { ALL_PRODUCTS } from '../types.ts';
import type { Constitution } from './constitution.ts';
import { buildReceipt, verifyReceipt, type Receipt } from './receipts.ts';
import type { ConstitutionDecision } from './constitution.ts';

/** State of the kill switch for one product. */
export interface ProductSwitchState {
  product: ProductId;
  engaged: boolean;
  receipt: Receipt;
  at: string;
}

/** Result of flipping the kill switch across the portfolio. */
export interface KillSwitchResult {
  engaged: boolean;
  at: string;
  products: ProductSwitchState[];
}

/**
 * In-memory store for kill-switch state per product. In production this would
 * be backed by darwin_* tables; this pure implementation is the control logic
 * that any persistence layer wraps.
 */
export class KillSwitchController {
  private constitutions: Map<ProductId, Constitution> = new Map();
  private receiptChains: Map<ProductId, Receipt[]> = new Map();

  /** Register a product's constitution for kill-switch control. */
  register(product: ProductId, constitution: Constitution): void {
    this.constitutions.set(product, constitution);
    if (!this.receiptChains.has(product)) {
      this.receiptChains.set(product, []);
    }
  }

  /** Get all registered products. */
  registeredProducts(): ProductId[] {
    return [...this.constitutions.keys()];
  }

  /** Flip the kill switch for ALL registered products. Returns receipts proving the action. */
  engage(at?: string): KillSwitchResult {
    return this._flip(true, at);
  }

  /** Disengage the kill switch for ALL registered products. */
  disengage(at?: string): KillSwitchResult {
    return this._flip(false, at);
  }

  /** Check if a specific product's kill switch is engaged. */
  isEngaged(product: ProductId): boolean {
    return this.constitutions.get(product)?.killSwitch === true;
  }

  /** Get the receipt chain for a product (for audit). */
  receiptsFor(product: ProductId): Receipt[] {
    return this.receiptChains.get(product) ?? [];
  }

  private _flip(engage: boolean, at?: string): KillSwitchResult {
    const now = at ?? new Date().toISOString();
    const products: ProductSwitchState[] = [];

    for (const [product, constitution] of this.constitutions) {
      constitution.killSwitch = engage;

      const chain = this.receiptChains.get(product) ?? [];
      const prev = chain[chain.length - 1] ?? null;

      const action: AgentAction = {
        product,
        type: engage ? 'kill_switch_engage' : 'kill_switch_disengage',
        actor: 'darwin:kill_switch_controller',
        subjectId: product,
        at: now,
      };

      const verdict: ConstitutionDecision = {
        decision: engage ? 'deny' : 'allow',
        ruleId: null,
        reason: engage ? 'kill_switch_engaged' : 'kill_switch_disengaged',
      };

      const receipt = buildReceipt({ chain: `killswitch:${product}`, action, verdict, prev, at: now });
      chain.push(receipt);
      this.receiptChains.set(product, chain);

      products.push({ product, engaged: engage, receipt, at: now });
    }

    return { engaged: engage, at: now, products };
  }
}
