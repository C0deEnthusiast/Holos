-- Migration 003: Drop maintenance_note column
-- Run AFTER 002_backfill_from_note.sql is verified correct

ALTER TABLE items DROP COLUMN IF EXISTS maintenance_note;
