from PIL import Image, ImageDraw
import requests
from io import BytesIO


def draw_red_cross(image_url):
    # Step 1: Load image from URL
    response = requests.get(image_url)
    image = Image.open(BytesIO(response.content)).convert("RGBA")

    # Step 2: Draw a red X (cross) on the image
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # Draw the two red diagonal lines
    draw.line((0, 0, width, height), fill="red", width=20)  # from top-left to bottom-right
    draw.line((0, height, width, 0), fill="red", width=20)  # from bottom-left to top-right

    # image.show()  # or image.save("output.png")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    img_data = buffer.read()
    return img_data
