-- MySQL integration fixture for Multi-DB inspector tests.
-- Database/schema name: iso_demo

CREATE DATABASE IF NOT EXISTS iso_demo
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE iso_demo;

CREATE TABLE tb_shared_patient (
  patient_id BIGINT NOT NULL COMMENT '환자 ID',
  patient_no VARCHAR(40) NOT NULL COMMENT '환자번호',
  patient_nm VARCHAR(100) NULL COMMENT '환자명',
  created_at DATETIME NULL COMMENT '등록일시',
  PRIMARY KEY (patient_id),
  UNIQUE KEY uq_shared_patient_no (patient_no),
  KEY ix_shared_patient_nm (patient_nm)
) ENGINE=InnoDB COMMENT='공유 환자 마스터';

CREATE TABLE tb_shared_order (
  order_id BIGINT NOT NULL COMMENT '오더 ID',
  patient_id BIGINT NOT NULL COMMENT '환자 FK',
  order_dt DATE NULL COMMENT '오더일',
  order_status VARCHAR(20) NULL COMMENT '오더상태',
  PRIMARY KEY (order_id),
  KEY ix_shared_order_patient (patient_id),
  CONSTRAINT fk_shared_order_patient
    FOREIGN KEY (patient_id) REFERENCES tb_shared_patient (patient_id)
) ENGINE=InnoDB COMMENT='공유 오더';

-- Composite primary key
CREATE TABLE tb_shared_code (
  cd_grp VARCHAR(20) NOT NULL COMMENT '코드그룹',
  cd_val VARCHAR(40) NOT NULL COMMENT '코드값',
  cd_nm VARCHAR(100) NULL COMMENT '코드명',
  PRIMARY KEY (cd_grp, cd_val)
) ENGINE=InnoDB COMMENT='공유 코드 (복합 PK)';

-- Composite foreign key
CREATE TABLE tb_shared_code_map (
  map_id BIGINT NOT NULL COMMENT '매핑 ID',
  cd_grp VARCHAR(20) NOT NULL COMMENT '코드그룹 FK',
  cd_val VARCHAR(40) NOT NULL COMMENT '코드값 FK',
  map_note VARCHAR(200) NULL COMMENT '매핑비고',
  PRIMARY KEY (map_id),
  KEY ix_shared_code_map_cd (cd_grp, cd_val),
  CONSTRAINT fk_shared_code_map
    FOREIGN KEY (cd_grp, cd_val) REFERENCES tb_shared_code (cd_grp, cd_val)
) ENGINE=InnoDB COMMENT='코드 매핑 (복합 FK)';
