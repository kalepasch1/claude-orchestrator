/**
 * Committee owner map — for each admin domain, the canonical committee name and chair role
 * that the deliberation pre-pass should attribute ownership to. Bridges the Python-side
 * committees.py adaptive panels with the TypeScript fleetAdmin deliberation module so both
 * layers agree on who "owns" a given action.
 *
 * Pure + zero-dep. Used by governFleetAction to attach the responsible committee name to
 * every approval card and receipt, enabling cross-app precedent keyed by domain committee.
 */
import type { AdminAction, AdminDomain } from './types.ts';

export interface CommitteeOwner {
  /** stable domain label — matches committees.py calibration keys */
  domain: AdminDomain;
  /** canonical committee name for this domain */
  committee: string;
  /** default chair role */
  chair: string;
  /** default seats for this domain's standing panel */
  defaultSeats: readonly string[];
}

export const DOMAIN_COMMITTEE_OWNERS: Record<AdminDomain, CommitteeOwner> = {
  users_access: {
    domain: 'users_access',
    committee: 'Identity & Access',
    chair: 'Identity Lead',
    defaultSeats: ['Access control specialist', 'KYC/identity analyst', 'Policy reviewer'],
  },
  billing: {
    domain: 'billing',
    committee: 'Billing & Finance',
    chair: 'Finance Lead',
    defaultSeats: ['Billing specialist', 'Unit-economics analyst', 'Risk reviewer'],
  },
  trust_safety: {
    domain: 'trust_safety',
    committee: 'Trust & Safety',
    chair: 'Trust Lead',
    defaultSeats: ['Abuse specialist', 'Content policy expert', 'Legal & Compliance reviewer'],
  },
  infra: {
    domain: 'infra',
    committee: 'Site Reliability',
    chair: 'SRE Lead',
    defaultSeats: ['Incident commander', 'Security specialist', 'Data integrity reviewer'],
  },
};

/** Locate the canonical committee owner for an action's domain. Fail-closed: unknown domain => infra owner. */
export function ownerCommitteeOf(action: Pick<AdminAction, 'domain'>): CommitteeOwner {
  return DOMAIN_COMMITTEE_OWNERS[action.domain] ?? DOMAIN_COMMITTEE_OWNERS['infra']!;
}
