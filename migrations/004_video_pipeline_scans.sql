-- ═══════════════════════════════════════════════════════════
-- Migration 004 — Video Pipeline: scans table additions
-- ═══════════════════════════════════════════════════════════
-- Adds columns required by the Agent 6 video walkthrough pipeline.
-- Safe to run multiple times (all use IF NOT EXISTS / IF NOT condition).
-- Run via: python migrate.py  OR  psql < migrations/004_video_pipeline_scans.sql

BEGIN;

-- scan_type: distinguish 'image' (single-photo) vs 'video' (walkthrough)
ALTER TABLE scans
    ADD COLUMN IF NOT EXISTS scan_type TEXT NOT NULL DEFAULT 'image'
    CHECK (scan_type IN ('image', 'video', 'item_link'));

-- frame_count: how many unique frames were processed
ALTER TABLE scans
    ADD COLUMN IF NOT EXISTS frame_count INTEGER NOT NULL DEFAULT 0;

-- items_detected: running count updated in real-time during pipeline
ALTER TABLE scans
    ADD COLUMN IF NOT EXISTS items_detected INTEGER NOT NULL DEFAULT 0;

-- items_saved: count of items auto-saved above confidence threshold
ALTER TABLE scans
    ADD COLUMN IF NOT EXISTS items_saved INTEGER NOT NULL DEFAULT 0;

-- processing_seconds: wall-clock duration of the full pipeline
ALTER TABLE scans
    ADD COLUMN IF NOT EXISTS processing_seconds NUMERIC(8, 1);

-- error: last error message if status = 'failed'
ALTER TABLE scans
    ADD COLUMN IF NOT EXISTS error TEXT;

-- ── Indexes ──────────────────────────────────────────────────────────────

-- Fast lookup of in-progress scans for a user (used by status polling)
CREATE INDEX IF NOT EXISTS idx_scans_user_status
    ON scans (user_id, status);

-- Fast lookup of video scans specifically
CREATE INDEX IF NOT EXISTS idx_scans_user_type
    ON scans (user_id, scan_type);

-- ── Realtime enable ──────────────────────────────────────────────────────
-- Supabase Realtime: subscribe to scans table changes for live progress
-- Run once per project (idempotent):
-- ALTER PUBLICATION supabase_realtime ADD TABLE scans;

COMMIT;
