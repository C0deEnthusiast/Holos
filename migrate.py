import os
import json
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

def migrate():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("Missing Supabase credentials.")
        return

    supabase = create_client(url, key)
    
    sql_commands = [
        "ALTER TABLE scans ADD COLUMN IF NOT EXISTS home_name TEXT DEFAULT 'My House';",
        "ALTER TABLE scans ADD COLUMN IF NOT EXISTS room_name TEXT DEFAULT 'General Room';",
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE items ALTER COLUMN scan_id DROP NOT NULL;",
        "INSERT INTO profiles (id, display_name) VALUES ('00000000-0000-0000-0000-000000000000', 'Demo User') ON CONFLICT (id) DO NOTHING;"
    ]
    
    print("--- MIGRATE: Updating Supabase Schema ---")
    
    # Attempt to run via RPC in case user has 'exec_sql' setup
    # If not, we fall back to resilience in app.py
    for cmd in sql_commands:
        print(f"Executing: {cmd}")
        try:
            # Common pattern for power users to have an 'exec_sql' function
            res = supabase.rpc('exec_sql', {'query': cmd}).execute()
            print(f"Success: {res.data}")
        except Exception as e:
            # If RPC doesn't exist, we explain why it couldn't run remotely
            if "function public.exec_sql(query text) does not exist" in str(e) or "404" in str(e):
                print(f"NOTICE: Could not run ALTER command directly. Please copy/paste the SQL from schema.sql into your Supabase SQL Editor.")
                break
            else:
                print(f"Error: {e}")

    print("\n--- MIGRATION COMPLETE ---")
    print("Note: If direct database update failed, the Holos app will use its 'resilient mode' and store location data in 'maintenance_note' until you manually run the SQL in migrations.")

if __name__ == "__main__":
    migrate()
