import win32gui
import math
from PIL import Image, ImageGrab, ImageChops, ImageFilter
# import numpy as np # Removed to avoid dependency issues on Py 3.14
# import cv2 # Removed to avoid dependency issues on Py 3.14

import utils

ROCKET_LEAGUE_NAME = "Rocket League"

# Reference resolution (the resolution the template images were taken at)
REF_WIDTH = 1920
REF_HEIGHT = 1080

# The Position of the score box at 1080p
# (Left, Top, Right, Bottom)
REF_BOX = (790, 10, 855, 85) 
REF_BOX_WIDTH = REF_BOX[2] - REF_BOX[0]
REF_BOX_HEIGHT = REF_BOX[3] - REF_BOX[1]
# The Reference Box is NOT in the center. It is slightly to the left (Left team score?)
# We need to calculate how far from the center it is.
REF_SCREEN_CENTER_X = REF_WIDTH // 2
REF_BOX_CENTER_X = REF_BOX[0] + (REF_BOX_WIDTH // 2)
REF_OFFSET_FROM_CENTER = REF_BOX_CENTER_X - REF_SCREEN_CENTER_X  # Should be negative (~ -137.5)

DIFFERENCE_SIMILARITY_THRESHOLD = 0.90
SAVED_IMAGE_SIMILARITY_THRESHOLD = 0.60

IMAGES_AMOUNT = 21
IMAGES_DIR = "images"

def load_images():
    result = []

    for i in range(IMAGES_AMOUNT):
        img = Image.open(utils.full_path(IMAGES_DIR, f"{i}.png"))
        # Pre-process the saved images exactly like we process the live screenshot
        # This ensures they have the same Mode (L), Size, and Visual Features (Thresholded)
        # We also ensure they are the correct reference size
        img = img.resize((REF_BOX_WIDTH, REF_BOX_HEIGHT), Image.Resampling.LANCZOS)
        img = manipulate_image(img)
        result.append(img)

    return result



def get_windows_by_title(title_text, exact = False):
    def _window_callback(hwnd, all_windows):
        all_windows.append((hwnd, win32gui.GetWindowText(hwnd)))
    windows = []
    win32gui.EnumWindows(_window_callback, windows)
    if exact:
        return [hwnd for hwnd, title in windows if title_text == title]
    else:
        return [hwnd for hwnd, title in windows if title_text in title]

def is_foreground(bbox):
    return all([i >= 0 for i in bbox])

def manipulate_image(img):
    # Convert to grayscale
    img = img.convert("L")
    
    # Thresholding: Convert pixels > 170 to 255 (white), others to 0 (black)
    # This matches the previous cv2.threshold(grayA, 170, 255, cv2.THRESH_BINARY)
    img = img.point(lambda p: 255 if p > 170 else 0)

    # Dilation: MaxFilter(3) is similar to varying dilation, makes white regions thicker
    img = img.filter(ImageFilter.MaxFilter(3))

    return img

def compare_images(img1, img2):
    # Calculate the root-mean-square difference between two images
    # We use ImageChops to get the absolute difference
    diff = ImageChops.difference(img1, img2)
    
    # Calculate RMS
    h = diff.histogram()
    sq = (value*((idx%256)**2) for idx, value in enumerate(h))
    sum_of_squares = sum(sq)
    rms = math.sqrt(sum_of_squares / float(img1.size[0] * img1.size[1]))

    # Previous logic returned 1.0 for perfect match (matchTemplate)
    # RMS returns 0 for perfect match.
    # We need to invert it to match the existing logic structure roughly, 
    # OR we can just return a similarity score based on RMS.
    
    # Simplification: Let's assume Maximum RMS is 255 (completely different)
    # Similarity = 1 - (RMS / 255)
    
    similarity = 1.0 - (rms / 255.0)
    return similarity


def get_score_img():
    hwnd = get_windows_by_title(ROCKET_LEAGUE_NAME)

    if not hwnd:
        raise RuntimeError(f"{ROCKET_LEAGUE_NAME} is not open")
    
    # bbox = win32gui.GetWindowRect(hwnd[0]) # Moved down

    # Strict Check: Only run if Rocket League is the ACTUAL active window.
    # This prevents the bot from reading your browser/discord when you Alt-Tab.
    if win32gui.GetForegroundWindow() != hwnd[0]:
        raise RuntimeError(f"{ROCKET_LEAGUE_NAME} is not in focus")

    bbox = win32gui.GetWindowRect(hwnd[0])

    if not is_foreground(bbox):
        raise RuntimeError(f"{ROCKET_LEAGUE_NAME} is minimized or off-screen")

    # Calculate the exact pixel coordinates for the score based on the window size
    window_width = bbox[2] - bbox[0]
    window_height = bbox[3] - bbox[1]

    # Calculate Scale Factor based on Height (UI usually scales with height)
    scale = window_height / REF_HEIGHT

    # Calculate the actual size of the box on this screen
    current_box_width = int(REF_BOX_WIDTH * scale)
    current_box_height = int(REF_BOX_HEIGHT * scale)

    # Calculate Position relative to computer center
    center_x = window_width // 2
    
    # Apply the scaled offset to find where the box should be on this screen
    scaled_offset = int(REF_OFFSET_FROM_CENTER * scale)
    box_center_x = center_x + scaled_offset

    # Coordinates are: (Left, Top, Right, Bottom)
    crop_box = (
        box_center_x - (current_box_width // 2),    # Left
        int(REF_BOX[1] * scale),                    # Top
        box_center_x + (current_box_width // 2),    # Right
        int(REF_BOX[1] * scale) + current_box_height# Bottom 
    )

    # Offset by the window position (in case game is not fullscreen at 0,0)
    final_box = (
        bbox[0] + crop_box[0],
        bbox[1] + crop_box[1],
        bbox[0] + crop_box[2],
        bbox[1] + crop_box[3]
    )

    img = ImageGrab.grab(final_box)

    # Resize the image back to the reference size so we can compare it with saved images
    # Image.LANCZOS is a high-quality resampling filter
    img = img.resize((REF_BOX_WIDTH, REF_BOX_HEIGHT), Image.Resampling.LANCZOS)

    return manipulate_image(img)
SAVED_IMAGES = load_images()
