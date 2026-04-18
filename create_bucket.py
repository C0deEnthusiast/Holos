import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if url and key:
    try:
        supabase = create_client(url, key)
        bucket_id = "scans"
        print(f"Creating bucket '{bucket_id}'...")
        # SDK v2 usually requires just id and options but maybe it needs name kwarg
        kwargs = {"name": "scans", "options": {"public": True}}
        try:
            res = supabase.storage.create_bucket("scans", **kwargs)
        except Exception as e:
            # fallback
            res = supabase.storage.create_bucket("scans", "scans")
        print("Bucket creation response:", res)
    except Exception as e:
        print("Error creating bucket:", e)
else:
    print("Missing credentials.")
