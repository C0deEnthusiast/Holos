import os
import google.generativeai as genai
from dotenv import load_dotenv
from PIL import Image
import json

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)
MODEL_ID = 'gemini-2.5-flash'

prompt = """
Analyze this room image. Identify the primary items of value or interest in the room 
(furniture, electronics, art, appliances). Do not list obvious architectural built-ins like walls or floors,
but focus on movable objects that would be part of a home inventory.

CRITICAL: For the "category" field, you MUST use a strict hierarchical format: "Main Category > Subcategory".
Examples: 
- "Furniture > Seating"
- "Furniture > Tables"
- "Electronics > Entertainment"
- "Appliances > Kitchen"
- "Decor > Art"
- "Decor > Rugs"
- "Media > Books"
Do not deviate from this format.

For each distinct item you identify, provide the name, category, make, specific model, and a rough estimated current market price in USD based on its condition and type. 

IMPORTANT METADATA INSTRUCTIONS:
- If you see brand logos or text on an item, use that information to accurately determine the `make` and `model`.
- For Books or Media: You MUST capture the Title as the `name`, the Author/Publisher as the `make`, and details like the Edition or ISBN number (if visible or inferable) in the `model` field.
- Analyze the context of the room (e.g., standard door sizes, standard ceiling heights) to provide an educated estimate of the physical dimensions of the item. Provide this in a specific, readable format (e.g., "60 x 30 x 15 inches", "8 ft tall"). 
- CRITICAL: You MUST provide an estimated dimension for EVERY item. Make a highly educated guess based on standard manufacturing sizes (e.g. a standard sofa is 84 inches, a standard dining chair is 36 inches tall). Do NOT say "cannot determine" or "N/A". Guessing is explicitly allowed and required.

If you cannot confidently identify the make or model, provide a generic description but be as specific as possible.

Return the response ONLY as a valid JSON array matching this schema:
[
  {
    "name": "string",
    "category": "string",
    "make": "string",
    "model": "string",
    "estimated_price_usd": "string",
    "estimated_dimensions": "string"
  }
]
"""

try:
    print(f"Testing Room Scan with key: {API_KEY[:10]}...")
    with Image.open("test_room.jpg") as image:
        model = genai.GenerativeModel(MODEL_ID)
        response = model.generate_content([prompt, image])
        print("Success!")
        print(response.text)
except Exception as e:
    import traceback
    with open("error.txt", "w") as f:
        f.write(traceback.format_exc())
    print("Failed. Check error.txt")
