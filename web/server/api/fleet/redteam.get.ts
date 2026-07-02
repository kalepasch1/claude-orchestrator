// GET /api/fleet/redteam — adversarial autonomy sweep: probe every domain ceiling with
// synthetic edge cases and report any that would auto-run with real harm potential (gaps).
import { runRedTeam } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(() => {
  const { findings, gaps } = runRedTeam();
  return { gaps, gapCount: gaps.length, probesRun: findings.length, clean: gaps.length === 0 };
});
