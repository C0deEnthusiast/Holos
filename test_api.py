import os
import google.generativeai as genai
from dotenv import load_dotenv
from PIL import Image

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)
MODEL_ID = 'gemini-2.5-flash'

try:
    print(f"Testing key: {API_KEY[:10]}...")
    with Image.open("test_tv.jpg") as image:
        model = genai.GenerativeModel(MODEL_ID)
        response = model.generate_content(["What is this?", image])
        print("Success:", response.text)
except Exception as e:
    import traceback
    with open("error.txt", "w") as f:
        f.write(traceback.format_exc())
    print("Failed. Check error.txt")
