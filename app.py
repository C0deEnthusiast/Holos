import os
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import scanner  # Import our existing scanning logic

app = Flask(__name__)

# Configure upload folder
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__line__ if '__line__' in locals() else __file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/scan', methods=['POST'])
def scan_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image parts in the request'}), 400
        
    files = request.files.getlist('image')
    
    if len(files) == 0 or files[0].filename == '':
        return jsonify({'error': 'No selected files'}), 400
        
    all_results = []
    errors = []

    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                # Process each room
                result_str = scanner.analyze_room(filepath)
                os.remove(filepath)
                
                if result_str:
                    # The scanner.py returns a JSON array string containing multiple items per image.
                    # We parse it here into a Python list so we can combine lists across all images.
                    import json
                    cleaned = result_str
                    if cleaned.startswith("```json"):
                         cleaned = cleaned.replace("```json\n", "").replace("```\n", "").replace("```", "")
                    
                    try:
                        items = json.loads(cleaned)
                        if isinstance(items, list):
                            all_results.extend(items)
                        else:
                            all_results.append(items)
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
        return jsonify({'error': 'Failed to process any images.', 'details': errors}), 500
        
    return jsonify({
        'success': True, 
        'data': all_results, # We now return a clean array of JS objects
        'errors': errors if errors else None
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
