#!/usr/bin/env bash
set -Eeuo pipefail

OWNER_PASSWORD="${DEMIS_OWNER_PASSWORD:-}"
RO_PASSWORD="${DEMIS_RO_PASSWORD:-}"

if [[ -z "$OWNER_PASSWORD" || -z "$RO_PASSWORD" ]]; then
  echo "DEMIS_OWNER_PASSWORD and DEMIS_RO_PASSWORD are required" >&2
  exit 1
fi

# This fixture is local/test only. Keep interpolation predictable and reject
# shell/SQL metacharacters rather than trying to escape arbitrary passwords.
if [[ ! "$OWNER_PASSWORD" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "DEMIS_OWNER_PASSWORD must contain only A-Z, a-z, 0-9, _ for this test fixture" >&2
  exit 1
fi
if [[ ! "$RO_PASSWORD" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "DEMIS_RO_PASSWORD must contain only A-Z, a-z, 0-9, _ for this test fixture" >&2
  exit 1
fi

sqlplus -s / as sysdba <<SQL
WHENEVER SQLERROR EXIT SQL.SQLCODE
ALTER SESSION SET CONTAINER=FREEPDB1;

BEGIN
  EXECUTE IMMEDIATE 'DROP USER DEMIS_RO CASCADE';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1918 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'DROP USER DEMIS_OWNER CASCADE';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1918 THEN RAISE; END IF;
END;
/

CREATE USER DEMIS_OWNER IDENTIFIED BY "$OWNER_PASSWORD"
  DEFAULT TABLESPACE USERS
  TEMPORARY TABLESPACE TEMP
  QUOTA UNLIMITED ON USERS;

CREATE USER DEMIS_RO IDENTIFIED BY "$RO_PASSWORD"
  DEFAULT TABLESPACE USERS
  TEMPORARY TABLESPACE TEMP;

GRANT CREATE SESSION TO DEMIS_OWNER;
GRANT CREATE SESSION TO DEMIS_RO;

EXIT;
SQL
