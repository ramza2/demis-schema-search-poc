-- Verify the DEMIS Oracle mock fixture after explicit bootstrap.
WHENEVER SQLERROR EXIT SQL.SQLCODE
SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF

ALTER SESSION SET CONTAINER=FREEPDB1;

DECLARE
  v_users  PLS_INTEGER;
  v_tables PLS_INTEGER;
  v_grants PLS_INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_users
    FROM DBA_USERS
   WHERE USERNAME IN ('DEMIS_OWNER', 'DEMIS_RO');

  SELECT COUNT(*) INTO v_tables
    FROM DBA_TABLES
   WHERE OWNER = 'DEMIS_OWNER';

  SELECT COUNT(*) INTO v_grants
    FROM DBA_TAB_PRIVS
   WHERE OWNER = 'DEMIS_OWNER'
     AND GRANTEE = 'DEMIS_RO'
     AND PRIVILEGE = 'SELECT';

  IF v_users != 2 OR v_tables != 25 OR v_grants != 25 THEN
    RAISE_APPLICATION_ERROR(
      -20001,
      'DEMIS fixture incomplete users=' || v_users ||
      ' tables=' || v_tables ||
      ' grants=' || v_grants
    );
  END IF;
END;
/

EXIT;
