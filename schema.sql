-- ═══════════════════════════════════════════════════════════════
-- Holos Database Schema (v2 — with proper item columns)
--
-- Run in Supabase SQL Editor to create tables from scratch.
-- For existing databases, use migrations/001_add_item_columns.sql.
-- ═══════════════════════════════════════════════════════════════

-- Create profiles table
CREATE TABLE profiles (
  id UUID PRIMARY KEY,
  display_name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Create scans table
CREATE TABLE scans (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES profiles(id) NOT NULL,
  original_image_url TEXT,
  home_name TEXT DEFAULT 'My House',
  room_name TEXT DEFAULT 'Living Room',
  status TEXT DEFAULT 'completed',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Create items table (v2 — all fields as proper columns)
CREATE TABLE items (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  scan_id UUID REFERENCES scans(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) NOT NULL,

  -- Core identification
  name TEXT,
  category TEXT,
  make TEXT,
  model TEXT,

  -- Pricing (primary market value)
  estimated_price_usd NUMERIC,
  estimated_dimensions TEXT,
  condition TEXT,

  -- Rich metadata (formerly in maintenance_note JSON blob)
  quantity INT DEFAULT 1,
  is_set BOOLEAN DEFAULT false,
  estimated_age_years TEXT,
  condition_notes TEXT,
  unit_price_usd TEXT,
  price_basis TEXT,
  confidence_score INT,
  identification_basis TEXT,

  -- Three-tier pricing: range strings for display
  resale_value_usd TEXT,
  retail_replacement_usd TEXT,
  insurance_replacement_usd TEXT,

  -- Three-tier pricing: numeric low/high for SQL aggregation
  resale_value_low NUMERIC,
  resale_value_high NUMERIC,
  retail_replacement_low NUMERIC,
  retail_replacement_high NUMERIC,
  insurance_replacement_low NUMERIC,
  insurance_replacement_high NUMERIC,

  -- Location (denormalized for fast queries)
  home_name TEXT DEFAULT 'My House',
  room_name TEXT DEFAULT 'General Room',

  -- Visual references
  bounding_box JSONB,
  thumbnail_url TEXT,
  suggested_replacements TEXT,

  -- Legacy JSON blob (kept for backward compat during migration)
  maintenance_note TEXT,

  -- Status & timestamps
  is_archived BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS (Row Level Security)
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;

-- Create policies so users can only view/edit their own data
CREATE POLICY "Users can manage their own profile"
ON profiles FOR ALL USING (auth.uid() = id);

CREATE POLICY "Users can manage their own scans"
ON scans FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can manage their own items"
ON items FOR ALL USING (auth.uid() = user_id);

-- Create a trigger to automatically create a profile for a new user
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.profiles (id, display_name)
  VALUES (new.id, new.raw_user_meta_data->>'full_name');
  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- ═══════════════════════════════════════════════════════════════
-- Performance indexes
-- ═══════════════════════════════════════════════════════════════

CREATE INDEX IF NOT EXISTS idx_scans_user_id ON scans(user_id);
CREATE INDEX IF NOT EXISTS idx_items_user_id ON items(user_id);
CREATE INDEX IF NOT EXISTS idx_items_scan_id ON items(scan_id);
CREATE INDEX IF NOT EXISTS idx_items_user_confidence ON items(user_id, confidence_score);
CREATE INDEX IF NOT EXISTS idx_items_user_category ON items(user_id, category);
CREATE INDEX IF NOT EXISTS idx_items_user_home_room ON items(user_id, home_name, room_name);

-- Full-text search
CREATE INDEX IF NOT EXISTS idx_items_search 
  ON items USING gin (
    to_tsvector('english', coalesce(name,'') || ' ' || coalesce(make,'') || ' ' || coalesce(model,''))
  );
