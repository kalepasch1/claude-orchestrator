// GET /api/fleet/constitution-verify — machine-checks the locked-dimension invariants across a
// bounded action space (money never auto-allows, identity/termination never auto, prod-data +
// secret rotation never auto). Returns any breach. Run this as a gate before shipping an amendment.
import { verifyConstitutionInvariants } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(() => verifyConstitutionInvariants());
