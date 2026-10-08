# Tutorial 25: Connect a Database

Put a PostgreSQL database behind governed, read-only tools: run PostgreSQL 16 in Docker,
give SAJHA a read-only login, add the connection, browse its catalog, mask a column, add a
curated view, watch the guard refuse a write, and ask SAJHA about the data. The design (the
statement guard, limits, masking, views) is in
[Data Connectors](../architecture/Data%20Connectors.md); every other kind is in the
[Data Connectors Reference Guide](../tools/enterprise/Data%20Connectors%20Reference%20Guide.md).

## What you'll learn

- How a connection becomes `shop__list_tables`, `shop__describe_table` and `shop__query`
- Why SAJHA's login should be read-only, and what still stops a write when it is not
- How to mask a column and what the guard then refuses
- How a curated view gives a typed tool with no SQL at all

## Prerequisites

- A SAJHA checkout with its virtual environment, and an admin sign-in
  ([Tutorial 1](TUTORIAL_01_getting_started.md))
- Docker
- Recommended: `pip install 'sqlglot'` (the guard's SQL parser; without it a stricter scanner
  is used)

## Steps

### 1. Run PostgreSQL with some data

```bash
docker run -d --rm --name shop-pg -e POSTGRES_PASSWORD=admin-pw -e POSTGRES_DB=shop \
  -p 55432:5432 postgres:16
docker exec -i shop-pg psql -U postgres -d shop <<'SQL'
CREATE TABLE customers (id int PRIMARY KEY, name text, email text);
COMMENT ON TABLE customers IS 'People who bought something';
INSERT INTO customers VALUES (1, 'Ann', 'ann@example.com'), (2, 'Bob', 'bob@example.com');
CREATE TABLE orders (id int PRIMARY KEY, customer_id int REFERENCES customers, status text,
                     total numeric(10,2), created_at date);
COMMENT ON COLUMN orders.status IS 'new, paid or shipped';
INSERT INTO orders SELECT g, 1 + g % 2, (ARRAY['new','paid','shipped'])[1 + g % 3], g * 1.5,
                          date '2026-01-01' + g FROM generate_series(1, 60) g;
CREATE ROLE sajha_ro LOGIN PASSWORD 'ro-pw';
GRANT USAGE ON SCHEMA public TO sajha_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO sajha_ro;
SQL
```

`sajha_ro` can read and nothing else: that is the first wall, and the one that does not
depend on SAJHA.

### 2. Start SAJHA with the password in the environment

SAJHA stores a *reference* to the password, never the password:

```bash
SHOP_DB_PASSWORD=ro-pw python run_sajha_web.py
```

### 3. Add the connection

Sign in as an administrator and open **Admin → Data connectors** (`/admin/connectors`).
Click **Add connection** and fill in:

| Field | Value |
|---|---|
| Id | `shop` |
| Kind | PostgreSQL |
| Title | `Shop database` |
| Description | `Orders and customers of the web shop.` |
| Host, Port, Database, User | `127.0.0.1`, `55432`, `shop`, `sajha_ro` |
| Password / key reference | `env:SHOP_DB_PASSWORD` |
| Max rows | `20` |
| Timeout (s) | `5` |
| Allowed schemas | `public` |

Click **Test**: the page shows *Connected: PostgreSQL 16...* and *2 allowed table(s)*. Click
**Save**. The card for *Shop database* lists three tools: `shop__list_tables`,
`shop__describe_table` and `shop__query`. They are ordinary registry tools: the Tools page,
MCP `tools/list`, API-key allow lists, policies and Ask SAJHA all see them. The record is at
`config/connectors/<id>.json` (here `shop.json`); open it and you will find
`"password": "env:SHOP_DB_PASSWORD"` and no password.

### 4. Browse the catalog

Click **Browse**, then **Describe** next to `public.orders`: the columns with their types and
the comment on `status`, the primary key, and three sample rows. The same comes from the tools:
open **Tools → shop__describe_table**, run it with `{"table": "orders"}`.

### 5. Query it

Run `shop__query` with

```json
{"sql": "SELECT status, count(*) AS n, sum(total) AS revenue FROM orders WHERE created_at >= :since GROUP BY status ORDER BY status",
 "params": {"since": "2026-02-01"}}
```

Three rows come back. `:since` is a placeholder: its value is bound by the driver, never written
into the SQL. Now run `{"sql": "SELECT * FROM orders"}`: 20 rows and `"truncated": true,
"truncated_reason": "rows"`, the connection's row cap.

### 6. Watch the guard

Each of these is refused before it reaches PostgreSQL, with the reason:

```sql
DELETE FROM orders
SELECT 1; DROP TABLE orders
SELECT pg_read_file('/etc/passwd')
COPY orders TO '/tmp/orders.csv'
SELECT * FROM pg_shadow
WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d
SELECT * FROM orders FOR UPDATE
```

And a statement that runs too long is cancelled at the 5-second limit:
`SELECT count(*) FROM generate_series(1, 10000000000)` answers *the query timed out after 5s
and was cancelled*. Every call, refused or not, is in the audit log (**Admin → Audit**) as
`connector.query` or `connector.rejected`, with the SQL's SHA-256.

The guard is not the only wall. Even if SAJHA signed in as `postgres` (try it: change the user
and the reference, **Save**), the session is read-only: a write that got past the guard would
fail with *cannot execute INSERT in a read-only transaction*.

### 7. Mask a column

**Edit** the connection and put in **Masking**:

```text
customers.email = partial
```

**Save**, then run `shop__query` with `{"sql": "SELECT * FROM customers"}`: the emails come back
as `***@******e.com`. Masking works on the column, so the guard now refuses the ways round it:
`SELECT upper(email) FROM customers`, `SELECT email AS e FROM customers` and
`SELECT id FROM customers WHERE email LIKE 'a%'` are all refused. Try `hide` instead of
`partial`: the column disappears from results and samples, and naming it is refused.

### 8. Add a curated view

Click **Add view** on the card and fill in:

| Field | Value |
|---|---|
| View name | `orders_by_status` |
| Table or view | `public.orders` |
| Order by | `created_at desc` |
| Columns to return | `id, status, total, created_at` |
| Filter 1 | column `status`, operators `eq` and `in` |
| Filter 2 | column `created_at`, operators `gte` and `lte` |

**Save view**. A fourth tool appears, `shop__orders_by_status`, with typed arguments `status`,
`status_in` (an array), `created_at_from`, `created_at_to` (dates) and `limit`, and no others.
Run it with `{"status_in": ["paid", "shipped"], "created_at_from": "2026-02-15", "limit": 5}`.
SAJHA writes the SQL; every value is bound. Untick **Caller SQL** on the connection and save:
`shop__query` goes away and the view stays, which is the shape to give callers that should not
write SQL at all.

### 9. Ask SAJHA

Open **Ask SAJHA** and ask **List the tables in the shop database**. The planner shortlists the
connection's tools by their descriptions (they carry the connection's description) and calls
`shop__list_tables`. The descriptions also tell a planner the order to work in: list the
tables, describe one, then query it with placeholders. With the built-in mock model
([Tutorial 10](TUTORIAL_10_ask_sajha.md)) that is as far as it goes, because the mock does not
write SQL. A real model (a provider and its key, see
[Intelligence Layer](../architecture/Intelligence%20Layer.md)) can follow the order on a
question such as **How much revenue did paid orders bring in February?**: describe `orders`,
write a SELECT with a `:since` placeholder, and cite the calls in its answer. If it writes SQL
the guard refuses, the refusal comes back to it as the tool's error, with the reason.

### 10. Clean up

On the card click **Remove** (the record and its tools go), then:

```bash
docker rm -f shop-pg
```

## The same from the command line

```bash
curl -s -X POST http://localhost:3002/api/connectors -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
    "id": "shop", "kind": "postgresql", "title": "Shop database",
    "options": {"host": "127.0.0.1", "port": 55432, "database": "shop", "user": "sajha_ro"},
    "secrets": {"password": "env:SHOP_DB_PASSWORD"},
    "limits": {"max_rows": 20, "timeout_seconds": 5}, "allow": {"schemas": ["public"]},
    "masking": [{"column": "customers.email", "mode": "partial"}]}'
curl -s -X POST http://localhost:3002/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "shop__query",
       "arguments": {"sql": "SELECT count(*) AS n FROM orders"}}}'
```

(Use the port your server listens on; the token comes from `POST /api/auth/login`.)

## What you learned

- A connection is a record with secret references; SAJHA generates its tools and governs them
  like any other tool
- Three walls stop writes: the statement guard, the read-only session, and the login's privileges
- Masking hides values and the guard stops the queries that would get round it
- A curated view is a typed tool with no SQL from the caller

## Next

- Connect a warehouse or a vector store: [Data Connectors Reference Guide](../tools/enterprise/Data%20Connectors%20Reference%20Guide.md)
- Constrain who may call `shop__query`: [Tutorial 20](TUTORIAL_20_policies_approvals_and_audit.md)
- Build tools whose work a model does: [Tutorial 26](TUTORIAL_26_build_an_llm_tool.md)

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
