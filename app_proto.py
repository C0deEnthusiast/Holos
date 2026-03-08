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
    """Helper to extract user_id from Supabase token or form data."""
    # 1. Check Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        if token == 'mock_token_for_prototype' or token == 'mock_token':
             return "00000000-0000-0000-0000-000000000000"
             
        if supabase:
            try:
                user_res = supabase.auth.get_user(token)
                if user_res.user:
                    return user_res.user.id
            except:
                pass
    
    # 2. Check Auth header (for direct API calls)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            res = supabase.auth.get_user(token)
            if res and res.user:
                return res.user.id
        except:
            pass
    
    # 3. Fallback to form field
    return request.form.get("user_id")

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
                            
                        # Add filename to help frontend mapping
                        for item in items:
                            item['original_filename'] = filename
                            # We also need to pass the scan context for manual saving later
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

@app.route('/api/items/save', methods=['POST'])
def save_item():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    try:
        data['user_id'] = user_id
        res = supabase.table("items").insert(data).execute()
        return jsonify({'success': True, 'data': res.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/items', methods=['GET'])
def get_user_items():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
        
    query = request.args.get('q', '')
    
    try:
        # We try to filter out archived items
        items_query = supabase.table("items").select("*, scans(home_name, room_name)").eq("user_id", user_id)
        
        # Try to filter by is_archived if it exists
        try:
            items_query = items_query.eq("is_archived", False)
        except:
            pass

        result = items_query.execute()
        data = result.data

        # If we had to use the fallback [ARCHIVED] note
        final_data = []
        for item in data:
            if item.get("maintenance_note") == "[ARCHIVED]":
                continue
            scan_info = item.get("scans", {})
            item["home_name"] = scan_info.get("home_name")
            item["room_name"] = scan_info.get("room_name")
            item.pop("scans", None)
            
            # Simple manual search filter if query provided
            if query:
                q = query.lower()
                matches = (
                    q in (item.get('name') or '').lower() or
                    q in (item.get('category') or '').lower() or
                    q in (item.get('make') or '').lower() or
                    q in (item.get('model') or '').lower()
                )
                if not matches:
                    continue
            
            final_data.append(item)
            
        return jsonify({'success': True, 'data': final_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
