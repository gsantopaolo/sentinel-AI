#region imports
import logging
import aiohttp
from PIL import Image, ExifTags
#endregion

logger = logging.getLogger(__name__)
async def download_image(url: str, download_path: str) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0'
    }
    temp_path = download_path + "_temp.jpg"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    # Ensure that the file is written in chunks to avoid loading it all in memory
                    with open(temp_path, 'wb') as f:
                        while True:
                            chunk = await response.content.read(1024)  # Read 1024 bytes
                            if not chunk:
                                break
                            f.write(chunk)
                    logger.info(f"🖼️ image downloaded successfully to {temp_path}")
                    original_image = Image.open(temp_path)
                    logger.info(f"🖼️ original image format {original_image.format}")

                    # Check if image is in RGBA mode and convert it to RGB for future processing
                    if original_image.mode == "RGBA":
                        logger.info(f"🖼️ Original image is in RBGA mode. converting image to RGB")
                        original_image = original_image.convert("RGB")

                    # Check if image is rotated and rotate it accordingly
                    try:
                        for orientation in ExifTags.TAGS.keys():
                            if ExifTags.TAGS[orientation]=='Orientation':
                                break

                        exif = original_image.getexif()

                        if exif[orientation] == 3:
                            original_image=original_image.rotate(180, expand=True)
                        elif exif[orientation] == 6:
                            original_image=original_image.rotate(270, expand=True)
                        elif exif[orientation] == 8:
                            original_image=original_image.rotate(90, expand=True)

                    except (AttributeError, KeyError, IndexError):
                        # cases: image don't have getexif
                        pass

                    original_image.save(download_path, "JPEG", quality=100)
                    return download_path
                else:
                    logger.error(f"failed to download image from {url}. Status code: {response.status}")
                    response.raise_for_status()
        except Exception as e:
            logger.exception(f"an error occurred while trying to download the image: {e}")
            raise