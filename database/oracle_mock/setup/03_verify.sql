-- Verify the DEMIS Oracle mock fixture after explicit bootstrap.
WHENEVER SQLERROR EXIT SQL.SQLCODE
SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF

ALTER SESSION SET CONTAINER=FREEPDB1;

DECLARE
  v_users             PLS_INTEGER;
  v_tables            PLS_INTEGER;
  v_grants            PLS_INTEGER;
  v_table_comments    PLS_INTEGER;
  v_col_comments      PLS_INTEGER;
  v_bad_comments      PLS_INTEGER;
  v_expected_comments PLS_INTEGER;
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

  SELECT COUNT(*) INTO v_table_comments
    FROM DBA_TAB_COMMENTS
   WHERE OWNER = 'DEMIS_OWNER'
     AND TABLE_TYPE = 'TABLE'
     AND COMMENTS IS NOT NULL;

  SELECT COUNT(*) INTO v_col_comments
    FROM DBA_COL_COMMENTS
   WHERE OWNER = 'DEMIS_OWNER'
     AND COMMENTS IS NOT NULL;

  SELECT
      (SELECT COUNT(*)
         FROM DBA_TAB_COMMENTS
        WHERE OWNER = 'DEMIS_OWNER'
          AND TABLE_TYPE = 'TABLE'
          AND COMMENTS IS NOT NULL
          AND INSTR(COMMENTS, UNISTR('\FFFD')) > 0)
    + (SELECT COUNT(*)
         FROM DBA_COL_COMMENTS
        WHERE OWNER = 'DEMIS_OWNER'
          AND COMMENTS IS NOT NULL
          AND INSTR(COMMENTS, UNISTR('\FFFD')) > 0)
    INTO v_bad_comments
    FROM DUAL;

  SELECT COUNT(*) INTO v_expected_comments
  FROM (
    SELECT 1
      FROM DBA_TAB_COMMENTS
     WHERE OWNER = 'DEMIS_OWNER'
       AND TABLE_NAME = 'TB_ADM_HIST'
       AND COMMENTS = UNISTR('\D658\C790 \C785\C6D0 \C774\B825')
    UNION ALL
    SELECT 1
      FROM DBA_TAB_COMMENTS
     WHERE OWNER = 'DEMIS_OWNER'
       AND TABLE_NAME = 'TB_LAB_RST'
       AND COMMENTS = UNISTR('\C784\C0C1\AC80\C0AC \ACB0\ACFC \C815\BCF4')
    UNION ALL
    SELECT 1
      FROM DBA_TAB_COMMENTS
     WHERE OWNER = 'DEMIS_OWNER'
       AND TABLE_NAME = 'TB_PT_MST'
       AND COMMENTS = UNISTR('\D658\C790 \AE30\BCF8 \C815\BCF4')
    UNION ALL
    SELECT 1
      FROM DBA_COL_COMMENTS
     WHERE OWNER = 'DEMIS_OWNER'
       AND TABLE_NAME = 'TB_PT_MST'
       AND COLUMN_NAME = 'PT_ID'
       AND COMMENTS = UNISTR('\D658\C790 \B0B4\BD80 \C2DD\BCC4\C790')
    UNION ALL
    SELECT 1
      FROM DBA_COL_COMMENTS
     WHERE OWNER = 'DEMIS_OWNER'
       AND TABLE_NAME = 'TB_RAD_RPT'
       AND COLUMN_NAME = 'IMPRESSION'
       AND COMMENTS = UNISTR('\C601\C0C1\AC80\C0AC \D310\B3C5 \ACB0\B860')
  );

  IF v_users != 2
     OR v_tables != 25
     OR v_grants != 25
     OR v_table_comments != 25
     OR v_col_comments != 13
     OR v_bad_comments != 0
     OR v_expected_comments != 5
  THEN
    RAISE_APPLICATION_ERROR(
      -20001,
      'DEMIS fixture incomplete users=' || v_users ||
      ' tables=' || v_tables ||
      ' grants=' || v_grants ||
      ' table_comments=' || v_table_comments ||
      ' column_comments=' || v_col_comments ||
      ' bad_comments=' || v_bad_comments ||
      ' expected_comments=' || v_expected_comments
    );
  END IF;
END;
/

EXIT;
