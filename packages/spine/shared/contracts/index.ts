/**
 * Public contract surface of the compounding code-generation platform spine.
 *
 * This barrel is the single import point for anyone building against the
 * platform. It is declaration-only — importing it pulls in no runtime code, so
 * a consumer can depend on the contract without depending on an implementation.
 *
 * The three core operations, and why they are separate:
 *   createCompound  — register a series of waves; never starts work.
 *   triggerWave     — start exactly one wave; returns on accept, not on finish.
 *   processEvent    — apply one observed state change; the only completion path.
 */
export type * from "./common.ts";
export type * from "./compound.ts";
export type * from "./wave.ts";
export type * from "./event.ts";

import type { CancelCompound, CreateCompound, GetCompound } from "./compound.ts";
import type { GetWave, ListWaves, TriggerWave } from "./wave.ts";
import type { ProcessEvent, SubscribeToEvents } from "./event.ts";

/**
 * The whole platform in one shape. An implementation satisfies this interface;
 * a caller depends on it. Nothing here has a body.
 */
export interface SpinePlatform {
  readonly createCompound: CreateCompound;
  readonly getCompound: GetCompound;
  readonly cancelCompound: CancelCompound;

  readonly triggerWave: TriggerWave;
  readonly getWave: GetWave;
  readonly listWaves: ListWaves;

  readonly processEvent: ProcessEvent;
  readonly subscribeToEvents: SubscribeToEvents;
}
