import locale
import time
import math
import sys
import os
import logging
from ultralytics import YOLO
from PIL import Image, ImageDraw
import numpy as np
from collections import Counter
import openai
import base64
import requests
from io import BytesIO
from pathlib import Path
import anthropic
import concurrent.futures



VISION_MODEL_GPT4O_MINI = "GPT-4O-MINI"
VISION_MODEL_HAIKU = "CLAUDE-3-HAIKU-20240307"
# claude-3-haiku-20240307
PROMPT_MESSAGE = ("Using the best of OCR and NLP, extract the text in the provided image, return the text you "
                  "recognized only, no comment. If you are not able to detect text return a blank string")

# region providers
# Base class for vision providers
class VisionProvider:
    def recognize_text(self, image, detail="auto"):
        raise NotImplementedError("This method should be implemented by subclasses")

    def calculate_price(self, prompt_tokens, completion_tokens):
        raise NotImplementedError("This method should be implemented by subclasses")


# OpenAI vision provider
class OpenAIProvider(VisionProvider):
    def __init__(self, api_key):
        self.logger = logging.getLogger(__name__)
        openai.api_key = api_key
        self.logger.info("🔑 initialized OpenAIProvider")

    def encode_image(self, image):
        try:
            buffered = BytesIO()
            image.save(buffered, format="JPEG")
            encoded_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
            self.logger.debug("🖼️ image successfully encoded")
            return encoded_image
        except Exception as e:
            self.logger.error(f"❌ error encoding image: {str(e)}")
            raise

    def recognize_text(self, image, detail="auto"):
        try:
            base64_image = self.encode_image(image)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {openai.api_key}"
            }
            payload = {
                "model": f"{VISION_MODEL_GPT4O_MINI.lower()}",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": PROMPT_MESSAGE
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": detail
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 300
            }

            self.logger.debug("📡 sending request to OpenAI API")
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()

            response_json = response.json()
            recognized_text = response_json['choices'][0]['message']['content']
            prompt_tokens = response_json['usage']['prompt_tokens']
            completion_tokens = response_json['usage']['completion_tokens']

            self.logger.debug("✔️ successfully recognized text")
            return recognized_text, prompt_tokens, completion_tokens
        except Exception as e:
            self.logger.error(f"❌ error during text recognition: {str(e)}")
            return "", 0, 0

    def calculate_price(self, prompt_tokens, completion_tokens):
        try:
            # Direct calculation without locale
            input_token_price_per_million = 0.150
            output_token_price_per_million = 0.600

            input_token_price = input_token_price_per_million / 1_000_000
            output_token_price = output_token_price_per_million / 1_000_000

            input_cost = prompt_tokens * input_token_price
            output_cost = completion_tokens * output_token_price
            total_cost = input_cost + output_cost

            self.logger.debug(
                f"💰 pricing calculated for {prompt_tokens} prompt tokens and {completion_tokens} completion tokens, {total_cost}")
            return total_cost
        except Exception as e:
            self.logger.error(f"❌ error calculating price: {str(e)}")
            raise


# Anthropic/Claude 3 provider (for Haiku)
class AnthropicProvider(VisionProvider):
    def __init__(self, api_key):
        self.logger = logging.getLogger(__name__)
        self.api_key = api_key
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.logger.info("🔑 initialized AnthropicProvider")

    def encode_image(self, image):
        try:
            buffered = BytesIO()
            image.save(buffered, format="JPEG")
            encoded_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
            self.logger.info("🖼️ image successfully encoded")
            return encoded_image
        except Exception as e:
            self.logger.error(f"❌ error encoding image: {str(e)}")
            raise

    def recognize_text(self, image, detail="auto"):
        try:
            base64_image = self.encode_image(image)

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": base64_image,
                            },
                        },
                        {
                            "type": "text",
                            "text": PROMPT_MESSAGE,
                        },
                    ],
                }
            ]

            self.logger.info("📡 sending request to Anthropic API")
            response = self.client.messages.create(
                model=f"{VISION_MODEL_HAIKU.lower()}",
                max_tokens=1024,
                messages=messages,
            )

            if not response.content or len(response.content) == 0:
                raise KeyError("invalid response from Claude 3: 'content' field is empty")

            recognized_text = response.content[0].text
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens

            self.logger.info("✔️ successfully recognized text")

            return recognized_text, prompt_tokens, completion_tokens
        except Exception as e:
            self.logger.error(f"❌ error during text recognition: {str(e)}")
            return "", 0, 0


    # def calculate_price(self, prompt_tokens, completion_tokens):
    #     try:
    #         locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    #
    #         input_token_price_per_million = 0.25
    #         output_token_price_per_million = 1.25
    #
    #         input_token_price = input_token_price_per_million / 1_000_000
    #         output_token_price = output_token_price_per_million / 1_000_000
    #
    #         input_cost = prompt_tokens * input_token_price
    #         output_cost = completion_tokens * output_token_price
    #         total_cost = input_cost + output_cost
    #
    #         self.logger.info(
    #             f"💰 pricing calculated for {prompt_tokens} prompt tokens and {completion_tokens} completion tokens")
    #         return total_cost
    #     except Exception as e:
    #         self.logger.error(f"❌ error calculating price: {str(e)}")
    #         raise

    def calculate_price(self, prompt_tokens, completion_tokens):
        try:
            # Direct calculation without locale
            input_token_price_per_million = 0.25
            output_token_price_per_million = 1.25

            input_token_price = input_token_price_per_million / 1_000_000
            output_token_price = output_token_price_per_million / 1_000_000

            input_cost = prompt_tokens * input_token_price
            output_cost = completion_tokens * output_token_price
            total_cost = input_cost + output_cost

            self.logger.debug(
                f"💰 pricing calculated for {prompt_tokens} prompt tokens and {completion_tokens} completion tokens")
            return total_cost
        except Exception as e:
            self.logger.error(f"❌ error calculating price: {str(e)}")
            raise
# endregion

class Coordinates:
    def __init__(self, x1: int, y1: int, x2: int, y2: int):
        self.x1: int = x1
        self.y1: int = y1
        self.x2: int = x2
        self.y2: int = y2

    def to_dict(self) -> dict[str, int]:
        return {
            'x1': self.x1,
            'y1': self.y1,
            'x2': self.x2,
            'y2': self.y2,
        }

class DetectionResult:
    def __init__(self,
                 box_idx: int,
                 coordinates: Coordinates,
                 dominant_color: str,
                 recognized_text: str,
                 image: any,  # Use `PIL.Image.Image` if using PIL images
                 prompt_tokens: int,
                 completion_tokens: int):
        self.box_idx: int = box_idx
        self.coordinates: Coordinates = coordinates
        self.dominant_color: str = dominant_color
        self.recognized_text: str = recognized_text
        self.image = image  # Type hint can be `PIL.Image.Image` or similar if specified
        self.prompt_tokens: int = prompt_tokens
        self.completion_tokens: int = completion_tokens

    def to_dict(self) -> dict[str, any]:
        return {
            'box_idx': self.box_idx,
            'coordinates': self.coordinates.to_dict(),
            'dominant_color': self.dominant_color,
            'recognized_text': self.recognized_text,
            'image': self.image,  # Adjust if serialization required
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
        }

class StickyDetector:
    def __init__(self, vision_model=VISION_MODEL_GPT4O_MINI, api_key=None,
                 model_path='/models/sticky_detector.pt', model_url="https://www.TO_BE_DEFINED"):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.model_path = model_path
        self.model_url = model_url
        self.model = None
        self.vision_model = vision_model

        try:
            self.logger.info(f"🔍 initializing StickyDetector with model {vision_model}")
            self.initialize_model()

            if self.vision_model == VISION_MODEL_GPT4O_MINI:
                self.provider = OpenAIProvider(api_key)
            elif self.vision_model == VISION_MODEL_HAIKU:
                self.provider = AnthropicProvider(api_key)
            else:
                raise ValueError("unsupported vision model.")
        except Exception as e:
            self.logger.error(f"❌ error during initialization: {str(e)}")
            raise

    def initialize_model(self):
        if not os.path.exists(self.model_path):
            # if the initial path (working for docker
            # is not found (you are running thi code locally) then
            # we adjust the path to match a local path
            self.model_path = 'models/sticky_detector.pt'
            if not os.path.exists(self.model_path):
                logger.info(f"📥 model not found at {self.model_path}, downloading from {self.model_url}...")
                self.download_model(self.model_url)
        self.model = YOLO(self.model_path)
        logger.info(f"🧠 model loaded successfully from {self.model_path}")

    def download_model(self, url):
        try:
            self.logger.info(f"📡 downloading model from {url}...")
            response = requests.get(url)
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            with open(self.model_path, 'wb') as model_file:
                model_file.write(response.content)
            self.logger.info("✔️ model downloaded successfully.")
        except Exception as e:
            self.logger.error(f"❌ failed to download the model: {str(e)}")
            raise

    def get_dominant_color(self, image):
        try:
            self.logger.debug(f"🎨 detecting image dominant color...")
            img = image.resize((50, 50))
            pixels = np.array(img).reshape(-1, 3)
            self.logger.debug("✔️ dominant color detected successfully.")
            return Counter(map(tuple, pixels)).most_common(1)[0][0]
        except Exception as e:
            self.logger.error(f"❌ failed to detect image dominant color: {str(e)}")
            raise

    def rgb_to_hex(self, rgb_color):
        return '#{:02x}{:02x}{:02x}'.format(rgb_color[0], rgb_color[1], rgb_color[2])

    def detect(self, image_path, save_original_with_boxes=False, vision_model=None, api_key=None):
        start_time = time.time()
        try:
            self.logger.info(f"🔍 starting object detection for {image_path}")

            # Only override if the provided vision model or API key is different from the initialized one
            if vision_model and vision_model != self.vision_model:
                if vision_model == VISION_MODEL_GPT4O_MINI:
                    self.provider = OpenAIProvider(api_key)
                elif vision_model == VISION_MODEL_HAIKU:
                    self.provider = AnthropicProvider(api_key)
                else:
                    raise ValueError("unsupported vision model.")
                # Update the model attribute in the class to reflect the change
                self.vision_model = vision_model  # Update the vision_model in the class

                self.logger.info(f"🔄 vision model updated to {self.vision_model} with new provider")

            # Run the YOLO model on the provided image path to detect objects
            results = self.model.predict(image_path)
            # Open the original image to prepare for drawing bounding boxes
            img = Image.open(image_path)
            # Create a copy of the image to draw bounding boxes on, leaving the original intact
            original_image_with_boxes = img.copy()
            # Prepare a drawing object to add rectangles (bounding boxes) to the copied image
            draw = ImageDraw.Draw(original_image_with_boxes)
            # Initialize an empty list to store details of each detected object
            detected_objects = []

            # Define a helper function to process each detected bounding box
            def process_box(box_idx, box):
                # Extract bounding box coordinates
                x1, y1, x2, y2 = box.int().tolist()
                # Crop the detected region from the original image using the bounding box
                cropped_image = img.crop((x1, y1, x2, y2))

                # Determine the dominant color of the cropped image region
                dominant_color_rgb = self.get_dominant_color(cropped_image)
                dominant_color_hex = self.rgb_to_hex(dominant_color_rgb)

                # Use the vision provider to recognize text in the cropped image
                recognized_text, prompt_tokens, completion_tokens = self.provider.recognize_text(cropped_image)

                # Create a Coordinates object
                coordinates = Coordinates(x1=x1, y1=y1, x2=x2, y2=y2)

                # Create and return a DetectionResult object
                return DetectionResult(
                    box_idx=box_idx,
                    coordinates=coordinates,
                    dominant_color=dominant_color_hex,
                    recognized_text=recognized_text,
                    image=cropped_image,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens
                )

            # Use a ThreadPoolExecutor for concurrent text extraction
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = []
                # Loop through each result from the YOLO model
                for result in results:
                    for box_idx, box in enumerate(result.boxes.xyxy):
                        futures.append(executor.submit(process_box, box_idx, box))

                for future in concurrent.futures.as_completed(futures):
                    detected_object = future.result()
                    detected_objects.append(detected_object)

                    if save_original_with_boxes:
                        draw.rectangle(
                            [(detected_object.coordinates.x1, detected_object.coordinates.y1),
                             (detected_object.coordinates.x2, detected_object.coordinates.y2)],
                            outline="#57e140", width=3
                        )

            if save_original_with_boxes:
                original_detected_file = os.path.join(os.path.dirname(image_path),
                                                      f"{Path(image_path).stem}__detected.jpg")
                original_image_with_boxes.save(original_detected_file)
                self.logger.debug(f"💾 saved image with bounding boxes to {original_detected_file}")

            total_cost = 0
            total_tokens = 0
            for obj in detected_objects:
                total_cost += self.provider.calculate_price(obj.prompt_tokens, obj.completion_tokens)
                total_tokens += obj.prompt_tokens + obj.completion_tokens
                # logger.info(
                #     f"box idx: {obj['box_idx']}, coordinates: {obj['coordinates']}, dominant color: {obj['dominant_color']}, text: {obj['recognized_text']}")

            # Log the total cost with a dollar sign in the formatted string
            logger.info(f"💰 total operation cost: ${total_cost:.12f} for {total_tokens:,} tokens")

            return detected_objects
        except Exception as e:
            self.logger.error(f"❌ error during detection: {str(e)}")
            raise
        finally:
            elapsed_time = time.time() - start_time
            self.logger.info(f"⏱️ detection completed in {elapsed_time:.2f} seconds")

    def save_detected_images(self, detected_objects, save_path):
        try:
            os.makedirs(save_path, exist_ok=True)
            for idx, obj in enumerate(detected_objects):
                image = obj.image
                file_name = f"detected_object_{idx}.jpg"
                save_image_path = os.path.join(save_path, file_name)
                image.save(save_image_path)
                self.logger.debug(f"💾 Saved {save_image_path}")
        except Exception as e:
            self.logger.error(f"❌ failed to save detected images: {str(e)}")
            raise

from dotenv import load_dotenv
# sample usage
load_dotenv()

# get log level from env
log_level_str = os.getenv('STICKY_LOG_LEVEL', 'ERROR').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
# get log format from env
log_format = os.getenv('STICKY_LOG_FORMAT', '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s')
# Configure logging
logging.basicConfig(level=log_level, format=log_format)

logger = logging.getLogger(__name__)
logger.info(f"Logging configured with level {log_level_str} and format {log_format}")
def main():
    if len(sys.argv) < 2:
        print("Usage: python detect_objects.py <image_path>")
        return

    image_path = sys.argv[1]
    vision_model = os.getenv("VISION_MODEL")
    openai_key = os.getenv("OPENAI_KEY")
    anthropic_key = os.getenv("ANTHROPIC_KEY")

    logger.info(f"Vision model: {vision_model}")

    # Choose the appropriate key based on the vision model
    api_key = openai_key if vision_model == VISION_MODEL_GPT4O_MINI else anthropic_key

    detector = StickyDetector(vision_model=vision_model, api_key=api_key)
    results = detector.detect(image_path=image_path, save_original_with_boxes=True)

    save_folder = str(Path(image_path).parent)
    detector.save_detected_images(results, save_folder)

    total_cost = 0
    for obj in results:
        total_cost += detector.provider.calculate_price(obj.prompt_tokens, obj.completion_tokens)
        logger.info(
            f"Box idx: {obj.box_id}, Coordinates: {obj.coordinates}, Dominant Color: {obj.dominant_color}, Text: {obj.recognized_text}")

    logger.info(f"Total cost for sticky note detection: ${total_cost:.12f}")


if __name__ == "__main__":
    main()
