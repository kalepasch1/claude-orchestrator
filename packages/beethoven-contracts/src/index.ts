/**
 * @beethoven/contracts — shared vocabulary for the fleet immune system.
 *
 * Contracts only: types, enum members and boundary validators. No actuators, no
 * services, no callers. Sibling tasks implement against these.
 *
 *   import { LaneState, RunnerStatus, laneSnapshotSchema } from '@beethoven/contracts';
 */
export * from './domain.ts';
export * from './schemas.ts';
