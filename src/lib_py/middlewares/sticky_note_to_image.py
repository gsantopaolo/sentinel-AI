from PIL import Image, ImageDraw, ImageFont
import logging

class StickyNoteImageCreator:
    def __init__(self, canvas_width=800, canvas_height=600):
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.logger = logging.getLogger(self.__class__.__name__)

    def generate_image(self, text_tiles):
        # Create a blank canvas with a white background
        canvas = Image.new("RGB", (self.canvas_width, self.canvas_height), "white")
        draw = ImageDraw.Draw(canvas)

        # Default font (you may specify a path to your preferred font file)
        font = ImageFont.load_default()

        # Draw each sticky note on the canvas
        for tile in text_tiles:
            # Calculate the bounding box of the sticky note
            x, y = tile.position_x, tile.position_y
            width, height = tile.width, tile.height
            background_color = tile.background_color
            font_color = tile.tile_content.font_color

            # Draw sticky note background
            draw.rectangle([x, y, x + width, y + height], fill=background_color)

            # Draw text line by line, with some padding
            padding = 10
            text_y = y + padding
            for line in tile.tile_content.text:
                draw.text((x + padding, text_y), line, fill=font_color, font=font)
                # Move down for the next line based on the text bounding box
                text_y += draw.textbbox((0, 0), line, font=font)[3] + 5
            self.logger.info("combined image generated successfully")
        return canvas

    def save_image(self, text_tiles, output_path="sticky_notes.png"):
        image = self.generate_image(text_tiles)
        image.save(output_path)




