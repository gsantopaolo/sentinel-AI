import colorsys
import json
import logging
import uuid

from PIL import Image
from lib_py.cb_client.cb import CollaboardClient
from lib_py.cb_client.cb_types import TextContent, Tile, TileType

# This is the default width of all tiles in the canvas and it is constant.
# In order to make a tile appear bigger or smaller in the canvas we need to adjust the scale of the tile.
canvas_default_tile_width = 200

def calculate_dimension_ratio_to_canvas_object(dimension):
    return canvas_default_tile_width / dimension

def get_average_sticky_note_width_and_height(results):
    widths = []
    heights = []
    for result in results:
        width = result.coordinates.x2 - result.coordinates.x1
        height = result.coordinates.y2 - result.coordinates.y1
        widths.append(width)
        heights.append(height)
    width_average = sum(widths) / len(widths)
    height_average = sum(heights) / len(heights)
    return round(min(width_average, height_average))

# Function to calculate scales for sticky notes and image based on the original image width and height
# img_final_scale is used to scale dimensions
# sticky_note_final_scale is used to scale sticky notes
def calculate_scales(results, image_width, image_height, image_scale):
    # Find the smallest dimension between image width and image height.
    smallest_dimension = min(image_width, image_height)

    # Calculate how much bigger or smaller the original image is compared to the canvas_default_tile_width (=200)
    img_to_canvas_ratio = calculate_dimension_ratio_to_canvas_object(smallest_dimension)

    # Calculate the average dimensions of the sticky notes.
    # Note: This implementation only creates square sticky notes, so width will always equal height
    average_sticky_note_width_height = get_average_sticky_note_width_and_height(results)

    # As sticky notes are always 200x200 we need to scale them up or down to get them to appear correct
    average_sticky_note_scale_to_canvas = average_sticky_note_width_height / canvas_default_tile_width

    # Scale sticky notes up or down depending on the img_to_canvas_ratio
    sticky_to_canvas_ratio = img_to_canvas_ratio * average_sticky_note_scale_to_canvas

    # Finally scale everything up or down based on the image scale provided by the client
    img_final_scale = img_to_canvas_ratio * image_scale
    sticky_note_final_scale = sticky_to_canvas_ratio * image_scale

    return sticky_note_final_scale, img_final_scale


class StickyNoteCreator:
    def __init__(self, origin_env: str):
        self.client = CollaboardClient(base_url=origin_env)
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def get_contrast_color(hex_color):
        """Generate a contrasting color for readability."""
        # Convert hex to RGB
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        # Convert RGB to HLS and determine luminance
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        # Choose black or white based on luminance
        return "#000000" if l > 0.5 else "#ffffff"

    def create_sticky_notes(self, user_id, project_id, results, image_path, scale = 1, target_coordinate_x=0.0, target_coordinate_y=0.0, dump_json=True):
        if not results:
            self.logger.error("❌ No sticky notes provided. Exiting...")
            return

        self.logger.info("🤖 creating sticky notes")
        sticky_notes: list[Tile] = []  # Initialize as an empty list

        img = Image.open(image_path)
        sticky_note_scale, img_scale = calculate_scales(results, img.width, img.height, scale)

        self.logger.info(f"👉 img.width {img.width}")
        self.logger.info(f"👉 img.height {img.height}")
        self.logger.info(f"👉 sticky_note_scale {sticky_note_scale}")
        self.logger.info(f"👉 img_scale {img_scale}")

        for result in results:
            # Calculate the position of the sticky note relative to the center
            # Note that we calculate the top left dimension of the sticky, as this is what is important to canvas
            offset_x = result.coordinates.x1 * img_scale
            offset_y = result.coordinates.y1 * img_scale
            position_x = target_coordinate_x + offset_x
            position_y = target_coordinate_y + offset_y

            background_color = result.dominant_color
            font_color = self.get_contrast_color(background_color)

            recognized_text = result.recognized_text
            text_lines = [line + "\n" for line in recognized_text.split("\n")] if recognized_text else ["\n"]

            self.logger.debug(f"position_x: {position_x}, position_y: {position_y}, "
                             f"recognized_text: {recognized_text}, text_lines: {text_lines}")

            self.logger.debug(f"recognized_text: {json.dumps(recognized_text)}")
            self.logger.debug(f"recognized_text: {json.dumps(text_lines)}")

            text_tile_content = TextContent(
                text=text_lines,
                font_family="Segoe UI",  # Adjust if you want to detect other fonts
                font_color=font_color,
                font_size=18,
                text_alignment=1,
                style=1,
                text_styles=[{"start": 0, "end": len(line), "style": {}} for line in text_lines]
            )

            # Create the sticky note tile at the calculated position
            text_tile = Tile(
                project_id=project_id,
                tile_id=uuid.uuid4(),
                type_tile=TileType.Text,
                position_x=position_x,
                position_y=position_y,
                scale_x=sticky_note_scale,
                scale_y=sticky_note_scale,
                height=200,
                width=200,
                z_index=0,
                rotation=0.0,
                background_color=background_color,
                tile_content=text_tile_content,
            )

            # Send the sticky note to Collaboard
            tile_result = self.client.create_tile(user_id=user_id, project_id=project_id, tile_data=text_tile)

            sticky_notes.append(text_tile)

        self.logger.info("✅ Sticky notes created successfully")
        # self.client.create_tiles(project_id=project_id, tile_list=sticky_notes)
        return sticky_notes



