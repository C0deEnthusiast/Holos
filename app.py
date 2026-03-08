import os
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from supabase import create_client, Client
import json
import scanner  # Import our existing scanning logic

# Load environment variables
load_dotenv(override=True)

app = Flask(__name__)

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase_secret = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") # Secret key for bypassing RLS in backend

if supabase_url and (supabase_secret or supabase_key):
    # Use Secret Key if available for backend operations, fallback to anon key
    active_key = supabase_secret if supabase_secret else supabase_key
    supabase: Client = create_client(supabase_url, active_key)
else:
    supabase = None
    print("WARNING: SUPABASE_URL or keys not found in environment.")

# Configure upload folder
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

# --- Supabase Auth Endpoints (REST API Wrapper) ---
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    full_name = data.get('full_name', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    if not supabase:
        # Mock successful registration if Supabase isn't setup
        return jsonify({'success': True})

    try:
        res = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {"data": {"full_name": full_name}}
        })
        return jsonify({'success': True, 'user': res.user.model_dump() if res.user else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    # --- HARDCODED TEST ACCOUNTS FOR TEAM PROTOTYPE ---
    test_accounts = {
        "admin@holos.com": "holos2026",
        "tester1@holos.com": "holos2026",
        "tester2@holos.com": "holos2026",
        "guest@holos.com": "holos2026",
        "demo@holos.com": "holos2026"
    }

    if email in test_accounts and password == test_accounts[email]:
        return jsonify({
            'success': True,
            'session': {'access_token': 'mock_token_for_prototype'},
            'user': {
                'email': email, 
                'user_metadata': {'full_name': email.split('@')[0].capitalize() + " (Test Account)"}
            }
        })
    # --------------------------------------------------

    if not supabase:
        # Fallback for local testing
        if password == 'password':
             return jsonify({
                'success': True,
                'session': {'access_token': 'mock_token'},
                'user': {'email': email, 'user_metadata': {'full_name': email.split('@')[0]}}
            })
        return jsonify({'error': 'Supabase not configured. Use password "password" for local testing.'}), 500

    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return jsonify({
            'success': True, 
            'session': res.session.model_dump() if res.session else None, 
            'user': res.user.model_dump() if res.user else None
        })
    except Exception as e:
        error_msg = str(e)
        if "Email not confirmed" in error_msg:
            error_msg = "Your email address has not been confirmed yet. Please check your inbox or use one of the Holos Test Accounts (e.g., admin@holos.com / holos2026)."
        print(f"Login Error: {e}")
        return jsonify({'error': error_msg}), 400

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    if not supabase:
        # Mock logout success
        return jsonify({'success': True})
    try:
        # Get token from header
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            supabase.auth.global_sign_out(token) # Sign out
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
# --- End Auth Endpoints ---

def get_current_user_id():
    """Helper to extract user_id and ensure a DB profile exists."""
    user_id = None
    auth_header = request.headers.get('Authorization')
    
    # 1. Try to get ID from Bearer Token
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        if token in ['mock_token_for_prototype', 'mock_token', 'null', '', None]:
            user_id = "00000000-0000-0000-0000-000000000000"
        elif supabase:
            try:
                user_res = supabase.auth.get_user(token)
                if user_res.user: 
                    user_id = user_res.user.id
            except: pass
            
    # 2. Fallback to form/default
    if not user_id:
        user_id = request.form.get("user_id") or "00000000-0000-0000-0000-000000000000"
    
    # 3. LINKAGE FIX: Ensure the Profile exists in the DB before proceeding
    if user_id and supabase:
        try:
            # Check if profile exists
            profile_check = supabase.table("profiles").select("id").eq("id", user_id).execute()
            if not profile_check.data:
                print(f"DEBUG: Profile missing for {user_id}. Attempting auto-creation...")
                profile_res = supabase.table("profiles").insert({
                    "id": user_id, 
                    "display_name": "Demo User" if user_id.startswith("0000") else "Holos User"
                }).execute()
                if profile_res.data:
                    print(f"DEBUG: Successfully created profile for {user_id}")
        except Exception as profile_err:
            print(f"CRITICAL ERROR: Failed to auto-create profile for {user_id}: {profile_err}")
            # Do NOT pass here, so we can see the error in logs
            
    return user_id

@app.route('/api/scan', methods=['POST'])
def scan_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image parts in the request'}), 400
        
    files = request.files.getlist('image')
    
    if len(files) == 0 or files[0].filename == '':
        return jsonify({'error': 'No selected files'}), 400
        
    all_results = []
    errors = []
    user_id = get_current_user_id()
    
    home_name = request.form.get("home_name", "My Home")
    room_name = request.form.get("room_name", "General Room")

    for file in files:
        if file and allowed_file(file.filename):
            original_filename = file.filename
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                # Process each room
                result_str = scanner.analyze_room(filepath)
                os.remove(filepath)
                
                if result_str == "QUOTA_EXHAUSTED":
                    errors.append(f"Google AI Studio Quota Exceeded. Please upgrade your API key or wait for the free limit to reset.")
                elif result_str:
                    # The scanner.py returns a JSON array string containing multiple items per image.
                    # We parse it here into a Python list so we can combine lists across all images.
                    cleaned = result_str.strip()
                    if cleaned.startswith("```"):
                         # Remove triple backticks and optional language identifier
                         lines = cleaned.split('\n')
                         if lines[0].startswith("```"):
                             lines = lines[1:]
                         if lines[-1].startswith("```"):
                             lines = lines[:-1]
                         cleaned = "\n".join(lines).strip()
                    
                    try:
                        items = json.loads(cleaned)
                        
                        # Ensure items is always a list
                        if not isinstance(items, list):
                            items = [items]
                            
                        # Add filename and location to help frontend mapping
                        for item in items:
                            item['original_filename'] = original_filename
                            # We store location directly in the item metadata 
                            # because the scans table might not have these columns yet.
                            item['home_name'] = home_name
                            item['room_name'] = room_name
                        
                        all_results.extend(items)
                    except json.JSONDecodeError:
                        errors.append(f"Failed to parse model output for {filename}")
                else:
                    errors.append(f"No response from model for {filename}")
                
            except Exception as e:
                if os.path.exists(filepath):
                     os.remove(filepath)
                errors.append(str(e))
        else:
            errors.append(f"Invalid file type for {file.filename if file else 'unknown'}")

    if not all_results and errors:
        main_error = errors[0] if any(keyword in errors[0] for keyword in ["Quota", "Model", "ClientError", "NOT_FOUND"]) else 'Failed to process any images.'
        return jsonify({'error': main_error, 'details': errors}), 500
        
    return jsonify({
        'success': True, 
        'data': all_results, # We now return a clean array of JS objects
        'errors': errors if errors else None
    })

@app.route('/api/items/<item_id>/archive', methods=['POST'])
def archive_item(item_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        # Check if is_archived column exists or use metadata as fallback
        # For this prototype, we'll try to update 'is_archived' and if it fails, we fall back to a metadata update
        try:
             supabase.table("items").update({"is_archived": True}).eq("id", item_id).eq("user_id", user_id).execute()
        except:
             # Fallback: maybe the column isn't there, so we prepend to maintenance note
             supabase.table("items").update({"maintenance_note": "[ARCHIVED]"}).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/items/<item_id>/unarchive', methods=['POST'])
def unarchive_item(item_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        if supabase:
            supabase.table("items").update({"is_archived": False}).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/items/save', methods=['POST'])
def save_item():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    try:
        # 1. Clean data and handle schema mismatches
        # 2. Extract Price safely
        price_str = str(data.get("estimated_price_usd") or "0").replace("$","").replace(",","")
        try:
            # Look for the first number in the string if it contains "About $50" or similar
            import re
            numbers = re.findall(r"[-+]?\d*\.\d+|\d+", price_str)
            price = float(numbers[0]) if numbers else 0.0
        except:
            price = 0.0

        to_save = {
            "user_id": user_id,
            "name": data.get("name"),
            "category": data.get("category"),
            "make": data.get("make"),
            "model": data.get("model"),
            "estimated_price_usd": price,
            "estimated_dimensions": data.get("estimated_dimensions"),
            "condition": data.get("condition"),
            "suggested_replacements": data.get("suggested_replacements"),
            "bounding_box": data.get("bounding_box"),
            "thumbnail_url": data.get("thumbnail_url"),
            "is_archived": data.get("is_archived", False),
            # We'll need a scan_id if we want a valid foreign key!
            # Let's create a minimal scan record first
            "maintenance_note": json.dumps({
                "home": data.get("home_name", "My House"),
                "room": data.get("room_name", "General Room")
            })
        }
        # LINKAGE FIX: Always ensure a Scan record exists for the item
        scan_payload = {
            "user_id": user_id,
            "status": "item_link",
            "home_name": data.get("home_name", "My House"),
            "room_name": data.get("room_name", "General Room")
        }
        
        try:
            scan_res = supabase.table("scans").insert(scan_payload).execute()
            if scan_res.data:
                to_save['scan_id'] = scan_res.data[0]['id']
            else:
                print("WARNING: Scan created but no ID returned.")
        except Exception as scan_err:
            print(f"NOTICE: Could not create scan record: {scan_err}. saving item without link.")

        # DEBUG LOGGING
        print(f"DEBUG: Attempting to save item for user {user_id}")
        print(f"DEBUG: Payload: {json.dumps(to_save, indent=2)}")

        res = supabase.table("items").insert(to_save).execute()
        
        print(f"DEBUG: Supabase response: {res}")

        if not res.data:
             return jsonify({
                 'error': 'Item saved but no data returned. Check RLS policies.',
                 'payload_sent': to_save
             }), 400
            
        return jsonify({'success': True, 'data': res.data[0]})
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"ERROR IN SAVE_ITEM: {error_msg}")
        traceback.print_exc()
        
        # Friendly hints for common errors
        if "profiles" in error_msg and "violates foreign key constraint" in error_msg:
             hint = "DEMO ERROR: You must create a profile for '00000000-0000-0000-0000-000000000000' in your Supabase 'profiles' table first."
             return jsonify({'error': f"{error_msg}. {hint}"}), 400
        
        if "scan_id" in error_msg and "violates not-null constraint" in error_msg:
             hint = "FIX: Your database still requires a scan_id. Please run this SQL in Supabase: 'ALTER TABLE items ALTER COLUMN scan_id DROP NOT NULL;'"
             return jsonify({'error': f"{error_msg}. {hint}"}), 400
        
        return jsonify({'error': f"Failed to save: {error_msg}"}), 500
             
        return jsonify({'error': error_msg}), 400

@app.route('/api/items', methods=['GET'])
def get_user_items():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
        
    query = request.args.get('q', '')
    show_archived = request.args.get('archived', 'false').lower() == 'true'
    
    try:
        # Fetch items joined with their scan location data
        # Use select("*, scans(*)") to get the home_name and room_name from the scans table
        items_query = supabase.table("items").select("*, scans(*)").eq("user_id", user_id)
        result = items_query.execute()
        data = result.data or []

        final_data = []
        for item in data:
            note = item.get("maintenance_note") or ""
            scan_info = item.get("scans") or {}
            
            # 1. Check archived status (column OR string marker)
            is_item_archived = (item.get("is_archived") == True) or (note == "[ARCHIVED]")
            item["is_archived"] = is_item_archived # Explicitly set for frontend
            
            # 2. Filter based on requested view (Archive vs Standard)
            if show_archived != is_item_archived:
                continue

            # 3. Resolve Location (prefer new columns, fallback to JSON in note)
            item["home_name"] = scan_info.get("home_name")
            item["room_name"] = scan_info.get("room_name")

            if not item["home_name"] or not item["room_name"]:
                if note and note.startswith("{"):
                    try:
                        meta = json.loads(note)
                        item["home_name"] = item["home_name"] or meta.get("home")
                        item["room_name"] = item["room_name"] or meta.get("room")
                    except: pass
            
            # Final Fallbacks
            item["home_name"] = item["home_name"] or "My House"
            item["room_name"] = item["room_name"] or "General Room"

            # 4. Search Filter
            if query:
                # Support multi-word search by ensuring every word matches
                search_terms = query.lower().split()
                searchable_text = f"{item.get('name')} {item.get('category')} {item.get('make')} {item.get('model')} {item['home_name']} {item['room_name']}".lower()
                
                if not all(term in searchable_text for term in search_terms):
                    continue
            
            final_data.append(item)
            
        return jsonify({'success': True, 'data': final_data})
    except Exception as e:
        import traceback
        print("ERROR IN GET_USER_ITEMS:")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
