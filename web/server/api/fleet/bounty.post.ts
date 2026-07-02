// POST /api/fleet/bounty  { submissions: GapSubmission[] }
// Adversarial bounty market: finders submit action shapes they claim auto-run above the harm
// threshold; each is validated against the REAL gate. Accepted findings pay out AND draft a
// constitution amendment that closes the gap. Security hardening as a self-funding market.
import { runBountyRound, type GapSubmission } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(async (event) => {
  const secret = getHeader(event, 'x-fleet-secret') ?? '';
  if ((process.env.FLEET_SHARED_SECRET ?? '') && secret !== process.env.FLEET_SHARED_SECRET) {
    throw createError({ statusCode: 401, message: 'bad_fleet_secret' });
  }
  const body = (await readBody(event)) as { submissions?: GapSubmission[] };
  if (!Array.isArray(body?.submissions)) throw createError({ statusCode: 400, message: 'submissions[] required' });
  return runBountyRound(body.submissions);
});
