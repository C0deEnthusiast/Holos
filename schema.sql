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

-- Create items table
CREATE TABLE items (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  scan_id UUID REFERENCES scans(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) NOT NULL,
  name TEXT,
  category TEXT,
  make TEXT,
  model TEXT,
  estimated_price_usd NUMERIC,
  estimated_dimensions TEXT,
  condition TEXT,
  bounding_box JSONB,
  maintenance_note TEXT,
  suggested_replacements TEXT,
  thumbnail_url TEXT,
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

-- Indexing for optimized queries
CREATE INDEX IF NOT EXISTS idx_scans_user_id ON scans(user_id);
CREATE INDEX IF NOT EXISTS idx_items_user_id ON items(user_id);
CREATE INDEX IF NOT EXISTS idx_items_scan_id ON items(scan_id);
