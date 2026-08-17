PROJECT: beethoven

- id: improve-queue-prevent-darwin-passport-conflicts
  title: improve-queue-prevent-darwin-passport-conflicts
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: Add focused gate tests with Python and TypeScript fixtures, then run npm --prefix packages/darwin-kernel test and the repository conflict-marker gate.
  prompt: |
    Prevent unresolved Git conflict markers from entering any production source, including TypeScript packages outside runner/. Add a repository-wide sentinel gate for exact conflict-marker lines, run language-appropriate syntax/type/test checks on every resolved file, and refuse merge/release promotion when either check fails. Preserve the current Darwin passport canonical-claim and mint-time-expiry behavior. Integrate the gate into continuous merger and release preflight without force-pushing or discarding either side.
    
    Queue context: The immediate Darwin conflict is resolved and tested; this task prevents the same class from reaching the live checkout again.
