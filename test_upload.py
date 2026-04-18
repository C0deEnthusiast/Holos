import os
import io
import mimetypes
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if url and key:
    supabase = create_client(url, key)
    # create a dummy file
    test_file_path = "test_image.jpg"
    with open(test_file_path, "wb") as f:
        f.write(b"fake image data")
    
    try:
        content_type, _ = mimetypes.guess_type(test_file_path)
        with open(test_file_path, "rb") as f:
            supabase.storage.from_("scans").upload(
                path="test_image.jpg",
                file=f,
                file_options={"content-type": content_type or "image/jpeg"}
            )
        print("Upload successful with file object")
    except Exception as e:
        print("Upload failed with file object:", e)
        
    try:
        supabase.storage.from_("scans").upload(
            path="test_image2.jpg",
            file=test_file_path,
            file_options={"content-type": content_type or "image/jpeg"}
        )
        print("Upload successful with filepath string")
    except Exception as e:
        print("Upload failed with filepath string:", e)
else:
    print("Missing credentials")
