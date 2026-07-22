
import score_detector
from PIL import Image

print("Capturing debug image...")
try:
    # Get the processed image
    img = score_detector.get_score_img()
    print("Capture successful!")
    
    # Save it so user can see
    print("Saving to debug_capture.png...")
    img.save("debug_capture.png")
    
    print("DONE! Please open 'debug_capture.png' and check if it clearly shows a Score Number.")
except Exception as e:
    print(f"Error: {e}")
    input("Press Enter to exit...")
