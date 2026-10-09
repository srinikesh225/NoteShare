-- =============================================================================
-- NoteShare - MySQL schema (Phase 1)
--
-- Target: MySQL 8.0.16 or newer (CHECK constraints are enforced from 8.0.16;
--         expression defaults such as (UTC_TIMESTAMP()) need 8.0.13+).
--
-- This file documents the same tables that models.py defines. seed.py creates
-- them through SQLAlchemy, so you normally do not need to run this file. To
-- use it directly, first create and select the database:
--
--     CREATE DATABASE noteshare CHARACTER SET utf8mb4;
--     USE noteshare;
--     SOURCE schema.sql;
--
-- It never drops anything: CREATE TABLE IF NOT EXISTS skips existing tables.
--
-- Conventions
--   * All timestamps are stored in UTC (DATETIME has no time zone).
--   * Foreign keys to users and subjects are ON DELETE RESTRICT: ban users
--     (is_banned) instead of deleting them; a subject with notes cannot be
--     deleted. Ratings and reports are ON DELETE CASCADE from notes.
--   * Constraint prefixes: uq_ unique, fk_ foreign key, ck_ check, ix_ index.
-- =============================================================================

-- 1. users --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INT          NOT NULL AUTO_INCREMENT,
    name          VARCHAR(100) NOT NULL,
    email         VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,   -- Werkzeug hash, never plain text
    role          ENUM('student', 'moderator', 'admin') NOT NULL DEFAULT 'student',
    branch        VARCHAR(100) NULL,
    year          SMALLINT     NULL,
    warnings      INT          NOT NULL DEFAULT 0,
    is_banned     BOOL         NOT NULL DEFAULT FALSE,
    created_at    DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),
    PRIMARY KEY (id),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_warnings_non_negative CHECK (warnings >= 0),
    CONSTRAINT ck_users_year_range CHECK (year IS NULL OR year BETWEEN 1 AND 6)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- 2. subjects -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subjects (
    id       INT          NOT NULL AUTO_INCREMENT,
    code     VARCHAR(20)  NOT NULL,
    name     VARCHAR(150) NOT NULL,
    semester SMALLINT     NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_subjects_code UNIQUE (code),
    CONSTRAINT ck_subjects_semester_range CHECK (semester BETWEEN 1 AND 12)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- 3. notes --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notes (
    id             INT          NOT NULL AUTO_INCREMENT,
    title          VARCHAR(200) NOT NULL,
    description    TEXT         NULL,
    file_path      VARCHAR(500) NOT NULL,   -- path under UPLOAD_FOLDER, not file contents
    subject_id     INT          NOT NULL,
    uploader_id    INT          NOT NULL,
    upload_date    DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),
    avg_rating     DOUBLE       NOT NULL DEFAULT 0,
    download_count INT          NOT NULL DEFAULT 0,
    status         ENUM('active', 'flagged', 'removed') NOT NULL DEFAULT 'active',
    PRIMARY KEY (id),
    INDEX ix_notes_status (status),
    INDEX ix_notes_subject_id (subject_id),
    INDEX ix_notes_uploader_id (uploader_id),
    CONSTRAINT fk_notes_subject FOREIGN KEY (subject_id)
        REFERENCES subjects (id) ON DELETE RESTRICT,
    CONSTRAINT fk_notes_uploader FOREIGN KEY (uploader_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT ck_notes_avg_rating_range CHECK (avg_rating BETWEEN 0 AND 5),
    CONSTRAINT ck_notes_download_count_non_negative CHECK (download_count >= 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- 4. ratings ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ratings (
    id         INT      NOT NULL AUTO_INCREMENT,
    note_id    INT      NOT NULL,
    student_id INT      NOT NULL,
    stars      SMALLINT NOT NULL,
    comment    TEXT     NULL,
    date       DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
    PRIMARY KEY (id),
    -- One rating per student per note (also serves lookups by note_id).
    CONSTRAINT uq_ratings_note_student UNIQUE (note_id, student_id),
    INDEX ix_ratings_student_id (student_id),
    CONSTRAINT fk_ratings_note FOREIGN KEY (note_id)
        REFERENCES notes (id) ON DELETE CASCADE,
    CONSTRAINT fk_ratings_student FOREIGN KEY (student_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT ck_ratings_stars_range CHECK (stars BETWEEN 1 AND 5)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- 5. reports ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    id           INT      NOT NULL AUTO_INCREMENT,
    note_id      INT      NOT NULL,
    reporter_id  INT      NOT NULL,
    reason       TEXT     NOT NULL,
    details      TEXT     NULL,       -- reporter's optional explanation (Phase 4)
    status       ENUM('open', 'resolved') NOT NULL DEFAULT 'open',
    action_taken TEXT     NULL,
    date         DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
    PRIMARY KEY (id),
    -- One report per reporter per note (also serves lookups by note_id).
    CONSTRAINT uq_reports_note_reporter UNIQUE (note_id, reporter_id),
    INDEX ix_reports_reporter_id (reporter_id),
    INDEX ix_reports_status (status),
    CONSTRAINT fk_reports_note FOREIGN KEY (note_id)
        REFERENCES notes (id) ON DELETE CASCADE,
    CONSTRAINT fk_reports_reporter FOREIGN KEY (reporter_id)
        REFERENCES users (id) ON DELETE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
