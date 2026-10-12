# Property Revenue Dashboard — Findings & Fixes

Debugging exercise only. Existing structure kept. Three planted bugs matched the three client reports.

## Symptoms → root causes

| Report | Root cause | File |
|---|---|---|
| Client A (Sunset): March totals wrong | Month window built in naive UTC, so Paris local March 1 (`2024-02-29 23:30 UTC`) was excluded. Working DB also failed open to a mock that mirrored that wrong total (`1000.00`). | `backend/app/services/reservations.py`, `backend/app/core/database_pool.py` |
| Client B (Ocean): sees another company’s numbers on refresh | Redis cache key was `revenue:{property_id}` with no tenant. `prop-001` exists for both tenants. | `backend/app/services/cache.py` |
| Finance: totals off by cents | API coerced `Decimal`/`NUMERIC` money through `float()`. | `backend/app/api/v1/dashboard.py`, `frontend/src/components/RevenueSummary.tsx` |

## Evidence (measured against seed + docker db/redis)

**Timezone / March (Sunset `prop-001`)**

```text
UTC-naive March SUM  = 1000.000   # excludes res-tz-1
Paris-local March SUM = 2250.000  # includes res-tz-1 (1250 + 333.333 + 333.333 + 333.334)
```

**Cache bleed**

```text
BUG key:  revenue:prop-001              # shared across tenants
FIX keys: revenue:tenant-a:prop-001
          revenue:tenant-b:prop-001
```

Ocean’s `prop-001` has **0** reservations. After Sunset warms the bad key, Ocean refresh returns Sunset’s `2250.000`.

**Float money**

```text
float(Decimal('0.1')) + float(Decimal('0.2')) != 0.3
Decimal('0.1') + Decimal('0.2') == Decimal('0.3')
```

API now returns `total_revenue` as a Decimal string.

## Fixes (minimal diffs)

1. **Cache** — `revenue:{tenant_id}:{property_id}`
2. **Timezone** — month bounds in property IANA timezone; monthly query filters with `tenant_id`
3. **DB pool** — connect via `settings.database_url` (compose `DATABASE_URL`), not missing `supabase_db_*` attrs
4. **Money** — keep `Decimal` → string at the API boundary; stop `float()` / `Math.round` money path

## How to verify

```bash
docker-compose up --build
```

1. Login as `sunset@propertyflow.com` / `client_a_2024` → Beach House Alpha (`prop-001`) shows **2250.00**, 4 bookings.
2. Login as `ocean@propertyflow.com` / `client_b_2024` → same property id shows Ocean’s data (0 / Mountain Lodge), **not** Sunset’s 2250 after refresh.
3. Raw payload `total_revenue` is a string like `"2250.000"`, not a float.

Optional script (db+redis up, backend venv):

```bash
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5438/propertyflow \
REDIS_URL=redis://127.0.0.1:6380/0 \
python backend/scripts/repro_bugs.py
```

## Loom outline (5–10 min)

See `LOOM_SCRIPT.md`.
