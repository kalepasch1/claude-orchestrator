// GET /api/fleet/coevolution — run the adversary↔defender loop to a fixed point and report
// the hardened safe-autonomy envelope (the largest autonomy that survives adversarial probing).
import { coEvolve } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(() => {
  const result = coEvolve();
  return { rounds: result.rounds, tightenings: result.tightenings, residualHarm: result.residualHarm, safe: result.residualHarm < 0.3 };
});
