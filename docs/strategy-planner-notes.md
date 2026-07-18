# Strategy Planner Notes

## QPD-Based Model Selection

The strategy planner selects models based on Quality Per Dollar (QPD) scores
tracked across recent task completions. Key considerations:

- **Cost zero local models** get infinite QPD when quality is non-zero, so quality
  thresholds matter more than raw QPD for local models
- **Explore vs exploit**: the pipeline uses exploration samples (configurable per
  route) to discover if cheaper models have improved
- **Task class affinity**: security tasks route to stronger models regardless of
  QPD since correctness is paramount

## Response Time Bottleneck

Operator feedback identifies response time during the remediation loop as a
measured bottleneck. Mitigation strategies:

- Pipeline scout pre-screens tasks for scope clarity before expensive model calls
- Debate compression reduces token overhead in multi-round exchanges
- Build fix routes can use faster flash models for iterative repair cycles
