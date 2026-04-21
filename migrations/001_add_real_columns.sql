-- Migration 001: Add real columns to items table (Holos v2 brief section 6)
-- Run this in Supabase SQL Editor

-- Tri-value pricing (cents, low/high ranges)
ALTER TABLE items ADD COLUMN IF NOT EXISTS quantity int DEFAULT 1;
ALTER TABLE items ADD COLUMN IF NOT EXISTS is_set boolean DEFAULT false;
ALTER TABLE items ADD COLUMN IF NOT EXISTS unit_price_cents bigint;
ALTER TABLE items ADD COLUMN IF NOT EXISTS resale_low_cents bigint;
ALTER TABLE items ADD COLUMN IF NOT EXISTS resale_high_cents bigint;
ALTER TABLE items ADD COLUMN IF NOT EXISTS retail_replacement_low_cents bigint;
ALTER TABLE items ADD COLUMN IF NOT EXISTS retail_replacement_high_cents bigint;
ALTER TABLE items ADD COLUMN IF NOT EXISTS insurance_replacement_low_cents bigint;
ALTER TABLE items ADD COLUMN IF NOT EXISTS insurance_replacement_high_cents bigint;
ALTER TABLE items ADD COLUMN IF NOT EXISTS pricing_rationale text;
ALTER TABLE items ADD COLUMN IF NOT EXISTS pricing_confidence numeric(3,2);
ALTER TABLE items ADD COLUMN IF NOT EXISTS pricing_last_refreshed_at timestamptz;

-- Identification confidence
ALTER TABLE items ADD COLUMN IF NOT EXISTS condition_confidence numeric(3,2);
ALTER TABLE items ADD COLUMN IF NOT EXISTS identification_confidence numeric(3,2);
ALTER TABLE items ADD COLUMN IF NOT EXISTS identification_basis text;
ALTER TABLE items ADD COLUMN IF NOT EXISTS condition_evidence text;
ALTER TABLE items ADD COLUMN IF NOT EXISTS bounding_box int[];
ALTER TABLE items ADD COLUMN IF NOT EXISTS bounding_box_coordinate_system text DEFAULT 'yxyx_1000';

-- Flags and review
ALTER TABLE items ADD COLUMN IF NOT EXISTS flags text[];
ALTER TABLE items ADD COLUMN IF NOT EXISTS user_confirmed boolean DEFAULT false;

-- AI audit columns
ALTER TABLE items ADD COLUMN IF NOT EXISTS ai_model_id text;
ALTER TABLE items ADD COLUMN IF NOT EXISTS ai_raw_response jsonb;

-- Overflow metadata
ALTER TABLE items ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}';

-- Timestamps
ALTER TABLE items ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

-- ai_calls table for token/cost tracking
CREATE TABLE IF NOT EXISTS ai_calls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES profiles(id) ON DELETE SET NULL,
  scan_id uuid REFERENCES scans(id) ON DELETE SET NULL,
  provider text NOT NULL DEFAULT 'google',
  model_id text NOT NULL,
  purpose text NOT NULL,
  input_tokens int,
  output_tokens int,
  cached_tokens int DEFAULT 0,
  cost_cents numeric(10,4),
  latency_ms int,
  success boolean NOT NULL DEFAULT true,
  error_code text,
  created_at timestamptz DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_items_user_archived ON items (user_id, is_archived);
CREATE INDEX IF NOT EXISTS idx_items_user_category ON items (user_id, category);
CREATE INDEX IF NOT EXISTS idx_items_user_insurance_value ON items (user_id, insurance_replacement_high_cents DESC);
CREATE INDEX IF NOT EXISTS idx_scans_user_status ON scans (user_id, status);
CREATE INDEX IF NOT EXISTS idx_ai_calls_user_created ON ai_calls (user_id, created_at DESC);

-- RLS for ai_calls
ALTER TABLE ai_calls ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='ai_calls' AND policyname='ai_calls_user_isolation'
  ) THEN
    CREATE POLICY ai_calls_user_isolation ON ai_calls FOR ALL USING (user_id = auth.uid());
  END IF;
END;
$$;
