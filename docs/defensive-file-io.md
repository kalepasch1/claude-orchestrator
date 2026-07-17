# Defensive File I/O Patterns

Standards for safe file operations across the orchestrator.

## Read pattern

```js
function safeRead(path, fallback = '') {
  try {
    if (!path) return fallback;
    const content = fs.readFileSync(path, { encoding: 'utf8', flag: 'r' });
    return content.slice(0, MAX_BYTES); // truncate at byte limit
  } catch (err) {
    if (err.code === 'ENOENT') return fallback;
    if (err.code === 'EACCES') return fallback;
    return fallback;
  }
}
```

## Rules

- Check multiple file locations before giving up
- Use `errors: 'replace'` for encoding issues
- Catch `ENOENT` separately from other errors
- Truncate at a byte limit to prevent memory pressure
- Do disk I/O outside any held locks
- Never raise on bad input (null, undefined, missing path)

## Resource gating

Gate resource expansion (new pool entries, large reads) on
`resource_governor.can_claim()` to prevent wedging under memory
pressure.
