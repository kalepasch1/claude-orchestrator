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

## Retry log
- 2026-09-09 (scheduled task): **not attempted** — no browser was reachable. Claude in Chrome
  extension reported "not connected"; the Control Chrome MCP and the in-app browser pane both
  require approval and no one was present to grant it during the unattended run.
  Capacity status therefore unchanged/unknown since 2026-07-02.
- 2026-09-09 (scheduled task, 2nd run): **not attempted, same blocker.** Claude in Chrome still
  "not connected" (list_connected_browsers returned empty, retried twice); the in-app browser pane
  requested access to cloud.oracle.com and was auto-declined with no one present.
  Capacity status still unknown since 2026-07-02. This task cannot succeed unattended until the
  Chrome extension is installed + signed in, or the OCI CLI/API is set up (see below).

## Unblock options (pick one)
1. Automatic: a scheduled Claude task retries the creation daily and notifies on success (set up 2026-07-02).
2. Instant: upgrade the OCI account to Pay As You Go — capacity constraint largely disappears and
   A1 within Always Free limits still bills $0 (billing decision is yours).
3. Manual: retry in console at off-peak hours with this doc.
4. Make the scheduled retry actually work headlessly — either install/sign in to the Claude in Chrome
   extension, or set up the OCI CLI (`oci setup config` + API key) so retries use
   `oci compute instance launch` instead of driving the console UI. The CLI path is the robust one:
   it returns the "Out of capacity" error directly and needs no browser or approvals.
