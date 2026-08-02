# Mutual Default Fund (MDF)

## Overview

The mutual default fund is a **non-custodial** mechanism for pricing member contributions based on credit quality and completeness. It does not involve the holding of customer funds or assets. All contributions are purely computational for settlement pricing purposes.

**No custody account is created or maintained.**

## Legal Positioning

This feature is an **internal administrative tool** for credit pricing. It is:
- **Non-custodial**: No funds are held or managed by the platform
- **Synthetic mechanism**: Embedded in documentation/paper only
- **Computational**: Purely mathematical pricing calculations
- **Internal-only**: Not exposed to end users as a customer-facing service
- **No regulated activity**: Does not constitute deposit-taking, custodial services, or financial advice

The mutual default fund is provided for **information and settlement pricing purposes only**. It does not constitute financial advice, investment advice, or a recommendation. Users are solely responsible for their participation decisions.

## Architecture

### Core Components

1. **Completeness-Based Pricing**: Member contribution priced inversely to completeness score
2. **Credit Gate**: Only members meeting credit threshold can participate
3. **Waterfall Logic**: Default losses absorbed via: defaulter margin → penalty → member assessments
4. **Audit Trail**: All decisions logged for compliance

### Pricing Formula

Member contribution (basis points) = base_bps × (1 - completeness_score / 100)

- Perfect completeness (100%): 0 bps
- Low completeness (50%): 5 bps (at 10 bps base)
- No completeness (0%): 10 bps (full base contribution)

### Credit Gate

Only members with credit score ≥ 700 can participate. This prevents toxic members from contaminating pricing.

### Default Waterfall

When a member defaults:
1. Defaulter's margin is absorbed first
2. Additional penalty applied (configurable rate)
3. Remaining loss spread to pool members pro-rata

## Configuration

All configuration uses `ORCH_MDF_*` environment variable prefix:

- `ORCH_MDF_ENABLED` (bool): Enable/disable MDF [default: false]
- `ORCH_MDF_CONTRIBUTION_BPS` (int): Base contribution in basis points [default: 10]
- `ORCH_MDF_COMPLETENESS_WEIGHT` (float): Weight for completeness in pricing [default: 1.0]
- `ORCH_MDF_CREDIT_GATE_THRESHOLD` (int): Minimum credit score for participation [default: 700]

No secrets or credentials are stored in configuration.

## Integration Points

- **Completeness Score Module**: Depends on `cc-completeness-score` for member scores
- **Acceptance Policy**: Members must pass `cc-acceptance-policy-and-matching` before MDF enrollment
- **Residual Exposure**: Works with `cc-residual-exposure-engine` to measure tail risk

## Existing Workflows Preserved

The MDF does not change:
- Credit scoring logic
- Settlement workflow (for normal non-default cases)
- Margin requirements and margin call logic
- Existing API endpoints

## Audit and Compliance

All MDF decisions are logged with:
- Member ID (opaque identifier only)
- Decision type (contribution calculated, member excluded)
- Reason/parameters
- Timestamp
- No personally identifiable information

## Feature Flag

MDF is **disabled by default**. Enable via:
```bash
export ORCH_MDF_ENABLED=true
```

## Risk Assessment

The mutual default fund reduces bilateral loss-given-default through mutualized contingent assessment. It does NOT:
- Create custody accounts or hold customer funds
- Require regulatory licensing or registration
- Constitute investment advice or recommendations
- Expose the platform to new regulatory categories
