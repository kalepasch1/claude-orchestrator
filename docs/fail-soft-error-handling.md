# Fail-Soft Error Handling Convention

All orchestrator engines and runners follow fail-soft semantics.

## Core principle

Errors during code execution or database queries must never wedge the
runner. They are caught and swallowed so the process can continue
serving other tasks.

## Implementation pattern

```js
try {
  const result = await riskyOperation();
  return result;
} catch (err) {
  log.warn({ err, context }, 'fail-soft: operation failed, returning default');
  return defaultValue; // "" for strings, [] for arrays, null for objects
}
```

## Return conventions on failure

| Type | Default |
|------|---------|
| String | `""` |
| Array | `[]` |
| Object | `null` |
| Number | `0` |
| Boolean | `false` |

## What NOT to swallow

- Authentication failures (401/403) — propagate these
- Data corruption signals — log at error level and alert
- Out-of-memory — let the process crash and restart
