/**
 * mergeTrainFastPath.ts — Fast-path check for merge train.
 * Stub: determines if a PR can skip the full merge queue.
 */
export const MERGE_TRAIN_FAST_PATH_ENABLED = process.env.MERGE_TRAIN_FAST_PATH_ENABLED === '1'

export interface FastPathCheck {
  prId: string
  canFastPath: boolean
  reason: string
}

export function checkFastPath(prId: string, hasDependencies: boolean, isGreen: boolean): FastPathCheck {
  const canFastPath = !hasDependencies && isGreen
  return {
    prId,
    canFastPath,
    reason: canFastPath ? 'No deps + green CI' : hasDependencies ? 'Has dependencies' : 'CI not green',
  }
}
