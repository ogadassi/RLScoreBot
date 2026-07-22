import os
import utils

try:
    sounds_path = utils.full_path("sounds")
    print(f"Calculated sounds path: {sounds_path}")
    
    if os.path.exists(sounds_path):
        print("Directory exists.")
        files = os.listdir(sounds_path)
        print(f"Found {len(files)} files:")
        for f in files:
            print(f" - {f}")
    else:
        print("Directory does NOT exist.")

except Exception as e:
    print(f"Error: {e}")
