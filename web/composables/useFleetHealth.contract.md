# Fleet health contract

The sentinel state is JSON with a top-level `db_up` flag. Only the literal value
`true` means the database is up; `false`, a missing field, an unreadable file, or
invalid JSON all mean down.

`GET /api/fleet-health` always returns `{ "db_up": boolean }`. File, permission,
and parsing errors fail soft as `{ "db_up": false }`; the route never throws for
sentinel read failures.

`useFleetHealth(): { dbUp: Ref<boolean | null>, refresh: () => Promise<void> }`
starts with `dbUp === null`. A successful refresh adopts the route's boolean;
network, authorization, or parsing failures set `dbUp` to `false` and do not
escape to the component.
