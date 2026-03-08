# Holos - AI-Powered Home Inventory & Scanning

Holos is a web application that uses Gemini Vision AI to analyze images of your home, identify items, estimate their value, and extract detailed metadata (like dimensions and book details).

## Contributors
- Satya Pushadapu
- Kevin Tang
- Joop Stark
- Rodolfo Martinez

---

## Setup Instructions for Team Members

### 1. Prerequisite
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
Create a file named `.env` in the root directory and add your Gemini API Key:
```text
GEMINI_API_KEY=your_api_key_here
```
> [!NOTE]
> You can get a free API key from [Google AI Studio](https://aistudio.google.com/).

### 6. Run the Application
```bash
python app.py
```
The application will be available at `http://127.0.0.1:5000`.

---

## Features
- **Batch Scanning**: Upload multiple images at once.
- **Hierarchical Categories**: Items are grouped into a tree structure.
- **Media Information**: Automatic extraction of book titles, authors, and ISBNs.
- **Dimension Estimation**: AI-based physical dimension estimation for assets.
- **Premium UI**: Sleek glassmorphism design with responsive components.