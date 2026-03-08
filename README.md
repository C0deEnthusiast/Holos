# Holos - AI-Powered Home Cataloging

**Your Home, Cataloged by AI.**

Holos is a premier, intelligent home inventory application that leverages Google's Gemini Vision AI to instantly identify, organize, and value your personal assets. Built with a sleek glassmorphism UI and a focus on simplicity, Holos turns the arduous task of home inventory management—crucial for insurance, moving, or personal organization—into a seamless experience.

![Holos Application Preview](/static/HOLOS.jpg)

## Why Holos?

Keeping track of your valuable items is often tedious. Holos solves this by allowing you to simply snap a picture of a room or item. Our AI takes over, automatically extracting:
- **Item Identification**: Name, Category, Make, and Model.
- **Automated Valuation**: Real-time estimated market value based on the item's condition.
- **Smart Parsing**: Context-aware extraction (e.g., Book Titles, Authors, ISBNs, and physical dimension estimations).

---

## Technical Highlights

- **Advanced AI Integration**: Powered by Gemini 2.5/1.5 Flash Vision models with custom temperature constraints for deterministic JSON extraction.
- **Modern Tech Stack**: Flask Backend, Vanilla JavaScript, and beautiful custom CSS.
- **Cloud Native**: Integrated with Supabase Auth (PostgreSQL) and Storage for secure, cloud-synced user profiles and image tracking.
- **SEO Optimized**: The web platform features a seamlessly integrated, SEO-optimized landing page designed to capture organic search traffic.

---

## Tech Stack

### HTML/CSS
### JavaScript
### Python
### Supabase and Supabase Storage (PostgreSQL)
### Gemini AI API
### Google Antigravity

---

## Setup Instructions for Developers

### 1. Prerequisites
Ensure you have **Python 3.10+** installed on your machine.

### 2. Clone the Repository
```bash
git clone git@github.com:C0deEnthusiast/Holos.git
cd Holos
```

### 3. Set up Virtual Environment
**Windows:**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables
Create a file named `.env` in the root directory and add your credentials:
```text
GEMINI_API_KEY=your_gemini_key
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
```

### 6. Run the Application
```bash
python app.py
```
The application will be available at `http://127.0.0.1:5000`.

---

## Contributors
- Satya Pushadapu
- Kevin Tang
- Rodolfo Martinez-Maldonado