-- Migration 002: Backfill real columns from maintenance_note JSON
-- Run AFTER 001_add_real_columns.sql

UPDATE items
SET
  resale_low_cents = CASE
    WHEN maintenance_note IS NOT NULL AND maintenance_note LIKE '{%'
     AND (maintenance_note::jsonb ? 'resale_low')
    THEN (maintenance_note::jsonb->>'resale_low')::bigint
    ELSE NULL
  END,
  resale_high_cents = CASE
    WHEN maintenance_note IS NOT NULL AND maintenance_note LIKE '{%'
     AND (maintenance_note::jsonb ? 'resale_high')
    THEN (maintenance_note::jsonb->>'resale_high')::bigint
    ELSE NULL
  END,
  retail_replacement_low_cents = CASE
    WHEN maintenance_note IS NOT NULL AND maintenance_note LIKE '{%'
     AND (maintenance_note::jsonb ? 'retail_low')
    THEN (maintenance_note::jsonb->>'retail_low')::bigint
    ELSE NULL
  END,
  retail_replacement_high_cents = CASE
    WHEN maintenance_note IS NOT NULL AND maintenance_note LIKE '{%'
     AND (maintenance_note::jsonb ? 'retail_high')
    THEN (maintenance_note::jsonb->>'retail_high')::bigint
    ELSE NULL
  END,
  identification_confidence = CASE
    WHEN maintenance_note IS NOT NULL AND maintenance_note LIKE '{%'
     AND (maintenance_note::jsonb ? 'confidence')
    THEN (maintenance_note::jsonb->>'confidence')::numeric
    ELSE NULL
  END,
  ai_model_id = CASE
    WHEN maintenance_note IS NOT NULL AND maintenance_note LIKE '{%'
    THEN maintenance_note::jsonb->>'model'
    ELSE NULL
  END,
  updated_at = now()
WHERE maintenance_note IS NOT NULL AND maintenance_note != '';
