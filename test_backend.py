import requests
import json

url = 'http://127.0.0.1:5000/api/scan'
files = [
    ('image', ('test_tv.jpg', open('test_tv.jpg', 'rb'), 'image/jpeg')),
    ('image', ('test_room.jpg', open('test_room.jpg', 'rb'), 'image/jpeg'))
]

print("Sending multiple files to Holos backend...")
response = requests.post(url, files=files)

print(f"Status Code: {response.status_code}")
try:
    data = response.json()
    print("Success:", data.get('success'))
    print(f"Number of items found: {len(data.get('data', []))}")
    print(json.dumps(data, indent=2))
except Exception as e:
    print("Error parsing response:", response.text)
