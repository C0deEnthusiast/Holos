-- Migration 005: Rename 'make' to 'brand' to match §6 and the v2 backend
DO $$ 
BEGIN 
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='items' AND column_name='make') THEN
        ALTER TABLE items RENAME COLUMN make TO brand;
    END IF;
END $$;
