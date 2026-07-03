# Oracle Cloud runner-2 — provisioning state (2026-07-02)

Fully configured in the OCI console (tenancy kalepasch, us-ashburn-1) but BLOCKED on
Oracle's side: "Out of capacity for VM.Standard.A1.Flex" in AD-1, AD-2, AD-3 (tried 4/24 and 2/12).
This is the well-known Always Free ARM squeeze; capacity frees up unpredictably (often early morning ET).

## Exact config to recreate (2 minutes)
- Name: orchestrator-runner-2 · Compartment: kalepasch (root)
- Image: Canonical Ubuntu 24.04 (aarch64-compatible) · Shape: VM.Standard.A1.Flex, 4 OCPU / 24 GB (Always Free)
- Networking: create new VCN + public subnet, auto-assign public IPv4
- SSH: paste public key from runner2_ed25519.pub (private key: runner2_ed25519 in this folder — NOT committed)
- Advanced > cloud-init: paste cloud-init.yaml from this folder

## After it boots
ssh -i scripts/cloud-vm/runner2_ed25519 ubuntu@<PUBLIC_IP>
then: clone the repo, scp runner/.env from the Mac, `claude login`, `nohup bash runner/keepalive.sh &`
(cloud-init already installed node22 + claude-code CLI + python deps; see /home/ubuntu/SETUP-NEXT.txt)

## Unblock options (pick one)
1. Automatic: a scheduled Claude task retries the creation daily and notifies on success (set up 2026-07-02).
2. Instant: upgrade the OCI account to Pay As You Go — capacity constraint largely disappears and
   A1 within Always Free limits still bills $0 (billing decision is yours).
3. Manual: retry in console at off-peak hours with this doc.
