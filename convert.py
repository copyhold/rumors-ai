import os
import base64
import io
from PIL import Image
from google import genai
from google.genai import types

# Initialize the client with your API Key
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def process_screenplay_folder(folder_path, output_filename="screenplay_output.html"):
    all_rows_html = ""

    # Supported image extensions
    valid_extensions = ('.png', '.jpg', '.jpeg', '.webp')
    image_files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith(valid_extensions)])

    if not image_files:
        print("No images found in the specified folder.")
        return

    prompt = """
    Identify the character names and the dialogue/actions in this screenplay image.

    Format the output as plain text in the following format:
    [Character Name]
    Dialogue or description text
    [another Character Name]
    Dialogue or description text

    - do not add page numbers into the output.
    - Important: Do NOT translate. Keep the Hebrew text exactly as it is.
    """

    for filename in image_files:
        print(f"Processing: {filename}...")
        file_path = os.path.join(folder_path, filename)

        # Load image and convert to bytes for the SDK
        with Image.open(file_path) as img:
            # We convert to RGB to ensure compatibility and save to a buffer
            img_byte_arr = io.BytesIO()
            img.convert("RGB").save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()

        # Generate response using the new SDK syntax
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                prompt,
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
            ]
        )

        # Clean potential markdown wrapping and append
        row_content = response.text.replace('```html', '').replace('```', '').strip()
        all_rows_html += row_content
        all_rows_html += "<tr><td>" + filename + "</td><td></td></tr>"

    # Build the final HTML document with RTL styling
    final_html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="he">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; background: #f9f9f9; }}
            table {{ width: 100%; border-collapse: collapse; background: #fff; }}
            th, td {{ border: 1px solid #ccc; padding: 12px; text-align: right; vertical-align: top; }}
            th {{ background-color: #eee; font-weight: bold; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
            .char-col {{ width: 20%; font-weight: bold; color: #d32f2f; }}
        </style>
    </head>
    <body>
        <h1>Screenplay Export</h1>
        <table>
            <thead>
                <tr>
                    <th class="char-col">דמות</th>
                    <th>טקסט / פעולה</th>
                </tr>
            </thead>
            <tbody>
                {all_rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"\nSuccess! File created: {output_filename}")

# Usage:
process_screenplay_folder("./page2")
