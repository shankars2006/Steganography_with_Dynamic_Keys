from stegano import lsb
from PIL import Image
import os

# Input and message
input_image = "input.jpg"
secret_message = "Hello World!"

# Convert image to PNG automatically if not already PNG
base, ext = os.path.splitext(input_image)
png_image = base + ".png"

if ext.lower() != ".png":
    # Convert to PNG
    img = Image.open(input_image).convert("RGB")
    img.save(png_image)
    print(f"🖼️ Converted '{input_image}' → '{png_image}'")
else:
    png_image = input_image

# Hide the message
secret = lsb.hide(png_image, secret_message)
secret.save("secret_image.png")
print("✅ Message hidden successfully in 'secret_image.png'")

# Reveal the message
revealed_message = lsb.reveal("secret_image.png")
print("🔍 Hidden Message:", revealed_message)
