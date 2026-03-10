import os
import json
from google import genai
from dotenv import load_dotenv
from PIL import Image
import traceback
import time

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("GEMINI_API_KEY is not set. Please check your .env file.")

client = genai.Client(api_key=API_KEY)
MODEL_ID = 'gemini-3-flash-preview'

def analyze_item(image_path: str) -> str:
    """Analyzes a single prominent item in an image."""
    print(f"Analyzing item in {image_path}...")
    
    prompt = """
    Analyze this image and identify the main object.
    Provide the name, category, make (brand), specific model (if identifiable), 
    and a rough estimated current market price in USD based on its condition and type. 
    If you cannot confidently identify the make or model, provide a generic description but be as specific as possible.
    
    Return the response ONLY as a valid JSON object matching this schema:
    {
      "name": "string",
      "category": "string",
      "make": "string",
      "model": "string",
      "estimated_price_usd": "string"
    }
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with Image.open(image_path) as image:
                response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=[prompt, image],
                    config={
                        'temperature': 0.0,
                        'response_mime_type': 'application/json'
                    }
                )
                return response.text
        except genai.errors.ClientError as e:
            if getattr(e, 'code', None) in (429, 503) or any(code in str(e) for code in ['429', '503']):
                if attempt < max_retries - 1:
                    print(f"Rate limit or high demand hit. Retrying in {(attempt + 1) * 15} seconds...")
                    time.sleep((attempt + 1) * 15)
                else:
                    print(f"Quota or retries exhausted for {MODEL_ID}: {e}")
                    return "API_UNAVAILABLE" if getattr(e, 'code', None) == 503 or '503' in str(e) else "QUOTA_EXHAUSTED"
            else:
                print(f"Error during analysis: {e}")
                traceback.print_exc()
                return f"SCAN_ERROR: {str(e)}"
        except Exception as e:
            print(f"Error during analysis: {e}")
            traceback.print_exc()
            return f"SCAN_ERROR: {str(e)}"

def analyze_room(image_path: str) -> str:
    """Analyzes a wide room image to identify multiple featured items."""
    print(f"\nScanning room in {image_path}...")
    
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
    Also include the item's condition, suggested modern replacements, estimated_dimensions, and a `bounding_box` array [ymin, xmin, ymax, xmax] using normalized coordinates (0-1000) for where the object is found in the image.
    
    IMPORTANT METADATA INSTRUCTIONS:
    - If you see brand logos or text on an item, use that information to accurately determine the `make` and `model`.
    - For Books or Media: You MUST capture the Title as the `name`, the Author/Publisher as the `make`, and details like the Edition or ISBN number (if visible or inferable) in the `model` field.
    - Analyze the context of the room (e.g., standard door sizes, standard ceiling heights) to provide an educated estimate of the physical dimensions of the item. Provide this in a specific, readable format (e.g., "60 x 30 x 15 inches", "8 ft tall"). 
    - CRITICAL: You MUST provide an estimated dimension for EVERY item. Make a highly educated guess based on standard manufacturing sizes (e.g. a standard sofa is 84 inches, a standard dining chair is 36 inches tall). Do NOT say "cannot determine" or "N/A". Guessing is explicitly allowed and required.
    
    If you cannot confidently identify the make or model, provide a generic description but be as specific as possible.
    IMPORTANT: Provide the physical object's real-world name. DO NOT return file names ending in .jpg, .png, etc.
    
    Return the response ONLY as a valid JSON array matching this schema:
    [
      {
        "name": "string",
        "category": "string",
        "make": "string",
        "model": "string",
        "estimated_price_usd": "string",
        "estimated_dimensions": "string",
        "condition": "string",
        "suggested_replacements": "string",
        "bounding_box": [number, number, number, number]
      }
    ]
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with Image.open(image_path) as image:
                response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=[prompt, image],
                    config={
                        'temperature': 0.0,
                        'response_mime_type': 'application/json'
                    }
                )
                return response.text
        except genai.errors.ClientError as e:
            if getattr(e, 'code', None) in (429, 503) or any(code in str(e) for code in ['429', '503']):
                if attempt < max_retries - 1:
                    print(f"Rate limit or high demand hit. Retrying in {(attempt + 1) * 15} seconds...")
                    time.sleep((attempt + 1) * 15)
                else:
                    print(f"Error during room scanning after {max_retries} attempts: Retries Exhausted ({e})")
                    return "API_UNAVAILABLE" if getattr(e, 'code', None) == 503 or '503' in str(e) else "QUOTA_EXHAUSTED"
            else:
                print(f"Error during room scanning: {e}")
                traceback.print_exc()
                return f"SCAN_ERROR: {str(e)}"
        except Exception as e:
            if any(key in str(e).lower() for key in ["429", "503", "resource has been exhausted", "quota", "unavailable"]):
                if attempt < max_retries - 1:
                    print(f"Rate limit or high demand hit. Retrying in {(attempt + 1) * 15} seconds...")
                    time.sleep((attempt + 1) * 15)
                else:
                    print(f"Error during room scanning after {max_retries} attempts: Retries Exhausted ({e})")
                    return "API_UNAVAILABLE" if "503" in str(e).lower() or "unavailable" in str(e).lower() else "QUOTA_EXHAUSTED"
            else:
                print(f"Error during room scanning: {e}")
                traceback.print_exc()
                return f"SCAN_ERROR: {str(e)}"

if __name__ == "__main__":
    print("--- Holos Prototype Initialized ---")
    
    # Test item analysis
    print("\n--- Single Item Test ---")
    item_result = analyze_item("test_tv.jpg")
    print(item_result)
    
    # Test room analysis
    print("\n--- Full Room Test ---")
    room_result = analyze_room("test_room.jpg")
    print(room_result)
