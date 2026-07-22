
import score_detector
from PIL import Image
import os

# Path to the image user uploaded (I will need to replace this with the actual path or just copy it)
USER_IMG_PATH = r"C:/Users/Administrator/.gemini/antigravity/brain/ee4c0cd5-5384-4cf3-a463-a501664fc766/uploaded_image_1765017804174.png"

print(f"Testing similarity for: {USER_IMG_PATH}")

try:
    # Load user image
    user_img = Image.open(USER_IMG_PATH)
    # Ensure it's in the same mode as the bot expects (it might be RGB from the upload)
    user_img = user_img.convert("L")
    user_img = user_img.resize((score_detector.REF_BOX_WIDTH, score_detector.REF_BOX_HEIGHT), Image.Resampling.LANCZOS)
    
    # We don't threshold it again if it's already thresholded, but the bot does. 
    # Let's see if the user's image is the raw capture or the processed result.
    # The user said "can you test with this picture" and uploaded "uploaded_image...".
    # Looking at the artifact, it is BLACK AND WHITE with a "3". 
    # If it is the output of "debug_view.py", then it is ALREADY processed.
    # So we should NOT process it again (thresholding 0/255 again is fine though).
    
    print("User image loaded.")

    print(f"\n--- Checking against {len(score_detector.SAVED_IMAGES)} saved templates ---")
    
    best_score = 0
    best_match_idx = -1

    for i, saved_img in enumerate(score_detector.SAVED_IMAGES):
        score = score_detector.compare_images(user_img, saved_img)
        print(f"Template {i}: Score = {score:.4f}")
        
        if score > best_score:
            best_score = score
            best_match_idx = i

    print("\n--- RESULTS ---")
    print(f"Best Match: Template {best_match_idx} with Score: {best_score:.4f}")
    print(f"Required Threshold: {score_detector.SAVED_IMAGE_SIMILARITY_THRESHOLD}")
    
    if best_score > score_detector.SAVED_IMAGE_SIMILARITY_THRESHOLD:
        print("PASS: This image would be detected as a goal!")
    else:
        print("FAIL: The score is too low. We need to lower the threshold.")

except Exception as e:
    print(f"Error: {e}")
