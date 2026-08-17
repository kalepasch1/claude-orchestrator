/**
 * Consumer check for `@spine/contracts` — compile-time only, no runtime.
 *
 * This file is deliberately NOT named `*.test.ts`: `npm test` runs
 * `node --test test/*.test.ts`, and there is nothing here to execute. It exists
 * so `npm run typecheck` fails if the spine contract surface stops being
 * consumable from this package.
 *
 * It proves three things the contract slice promised:
 *   1. a sibling package can import the named types from the barrel;
 *   2. the barrel is type-only — importing it pulls in no runtime value;
 *   3. spine's `PassportData` stays structurally assignable from the kernel's
 *      own `Passport`, which is the whole reason the spine restates the shape
 *      instead of depending on this package.
 *
 * (3) is the one that will actually catch a regression. The spine cannot import
 * `@darwin/kernel` — it is declaration-only with zero dependencies — so nothing
 * on that side can detect drift. The check has to live here, pointing the other
 * way.
 */

import type {
  PassportData,
  PipelineStage,
  PipelineStructure,
} from '@spine/contracts';
import type { Passport } from '../src/passport/passport.ts';

/** Fails to compile if `T` is not assignable to `U`. */
type Assignable<T extends U, U> = T;

/**
 * The kernel's Passport must satisfy the spine's PassportData. If someone adds
 * a required field to `Passport`, or narrows one the spine declares wider, this
 * line stops compiling — which is the signal, since the two shapes are
 * maintained separately on purpose.
 */
type _PassportFlowsToSpine = Assignable<Passport, PassportData>;

/** A pipeline's stages must be exactly the stage descriptor — no widening. */
type _StagesAreStages = Assignable<
  PipelineStructure['stages'][number],
  PipelineStage
>;

/**
 * A stage's dependencies must reference stage ids, not raw strings. Branding is
 * the only thing stopping an unrelated id from being passed positionally, so it
 * is worth asserting rather than assuming.
 */
type _DepsAreBranded = Assignable<
  PipelineStage['dependsOn'][number],
  PipelineStage['id']
>;

export type {
  _DepsAreBranded,
  _PassportFlowsToSpine,
  _StagesAreStages,
};
