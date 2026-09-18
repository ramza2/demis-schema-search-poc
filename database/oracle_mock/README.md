# Oracle DEMIS Mock

Internal test Oracle Free fixture for DEMIS Schema Analyzer on the GPU server.

It recreates the physical mock schema previously analyzed as:

- service: `FREEPDB1`
- owner schema: `DEMIS_OWNER`
- read-only analysis user: `DEMIS_RO`
- 25 tables
- 206 columns
- 40 foreign-key relations
- 19 non-constraint indexes
- 25 table comments
- 13 column comments
- expected Schema Analyzer fingerprint: `97ac64035d5d73ab80feb5c99c9875e247d25c375bec61a7672a3c38137c0df0`

The fixture contains schema metadata only. It does not seed patient rows.

## Start

The LAN deployment script starts it when:

```text
ORACLE_TEST_ENABLED=true
```

in `.env.lan`.

From the backend container, register the target using:

```text
DBMS: Oracle
Host: oracle-test
Port: 1521
Database / Service: FREEPDB1
Default Schema: DEMIS_OWNER
Username: DEMIS_RO
Password: value of DEMIS_ORACLE_RO_PASSWORD in .env.lan
```

The LAN deployment does not publish Oracle to the GPU server host or LAN.
Schema Analyzer reaches it only through the internal Docker network at `oracle-test:1521`.
Use `docker exec` for server-side diagnostics if needed.

Oracle's setup scripts run only when the Oracle data volume is first initialized.
To rebuild the mock schema from scratch, remove the Oracle test volume and redeploy.

Do not use these fixture credentials or this database in production.
