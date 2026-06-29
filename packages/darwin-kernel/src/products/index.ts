/**
 * Per-product wiring registry. Each product exposes: a starter Constitution,
 * its published Capabilities, locked dimensions, and passport-claim builders.
 * Import the one you need from `@darwin/kernel/products`.
 */
export * as tomorrow from './tomorrow.ts';
export * as pareto from './pareto.ts';
export * as smarter from './smarter.ts';
export * as galop from './galop.ts';
export * as hisanta from './hisanta.ts';
export * as apparently from './apparently.ts';

import type { ProductId } from '../types.ts';
import type { Constitution } from '../governance/constitution.ts';
import type { CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';
import { tomorrowConstitution, tomorrowCapabilities } from './tomorrow.ts';
import { paretoConstitution, paretoCapabilities } from './pareto.ts';
import { smarterConstitution, smarterCapabilities } from './smarter.ts';
import { galopConstitution, galopCapabilities } from './galop.ts';
import { hisantaConstitution, hisantaCapabilities } from './hisanta.ts';
import { apparentlyConstitution, apparentlyCapabilities } from './apparently.ts';

/** Get a product's starter constitution by id. */
export function constitutionFor(product: ProductId): Constitution | null {
  switch (product) {
    case 'tomorrow': return tomorrowConstitution();
    case 'pareto': return paretoConstitution();
    case 'smarter': return smarterConstitution();
    case 'galop': return galopConstitution();
    case 'hisanta': return hisantaConstitution();
    case 'apparently': return apparentlyConstitution();
    default: return null;
  }
}

/** Every capability published across the whole portfolio (for one-shot registry seeding). */
export function allCapabilities(baseUrlByProduct: Partial<Record<ProductId, string>> = {}): CapabilitySpec[] {
  return [
    ...tomorrowCapabilities(baseUrlByProduct.tomorrow ?? ''),
    ...paretoCapabilities(baseUrlByProduct.pareto ?? ''),
    ...smarterCapabilities(baseUrlByProduct.smarter ?? ''),
    ...galopCapabilities(baseUrlByProduct.galop ?? ''),
    ...hisantaCapabilities(baseUrlByProduct.hisanta ?? ''),
    ...apparentlyCapabilities(baseUrlByProduct.apparently ?? ''),
  ];
}
