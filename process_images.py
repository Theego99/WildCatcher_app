import time
import numpy as np
import requests

from io import BytesIO
from PIL import Image
from load_detector import load_detector

def process_images(
    im_files,
    detector,
    confidence_threshold,
    use_image_queue=False,
    quiet=False,
    image_size=None,
    checkpoint_queue=None,
    include_image_size=False,
    include_image_timestamp=False,
    include_exif_data=False,
    augment=False,
):

    # If detector is a path (string), load it
    if isinstance(detector, str):
        start_time = time.time()
        detector = load_detector(detector)
        elapsed = time.time() - start_time
        print(f"Loaded model (batch level) in {elapsed:.2f} seconds")

    results = []

    for im_file in im_files:
        result = process_image(
            im_file,
            detector,
            confidence_threshold,
            quiet=quiet,
            image_size=image_size,
            include_image_size=include_image_size,
            include_image_timestamp=include_image_timestamp,
            include_exif_data=include_exif_data,
            augment=augment,
        )

        if checkpoint_queue is not None:
            checkpoint_queue.put(result)
        results.append(result)

    return results


def process_image(
    im_file,
    detector,
    confidence_threshold,
    image=None,
    quiet=False,
    image_size=None,
    include_image_size=False,
    include_image_timestamp=False,
    include_exif_data=False,
    skip_image_resizing=False,
    augment=False,
):
    if not quiet:
        print(f"Processing image {im_file}")

    # Initialize result with file name and empty detections
    result = {"file": im_file, "detections": []}

    if image is None:
        try:
            image = load_image(im_file)
        except Exception as e:
            if not quiet:
                print(f"Image {im_file} cannot be loaded. Exception: {e}")
            result["failure"] = "Failure image access"
            return result

    try:
        detection_result = detector.generate_detections_one_image(
            image,
            im_file,
            detection_threshold=confidence_threshold,
            image_size=image_size,
            skip_image_resizing=skip_image_resizing,
            augment=augment,
        )
        # Merge detection_result into result
        result.update(detection_result)
    except Exception as e:
        if not quiet:
            print(f"Image {im_file} cannot be processed. Exception: {e}")
        result["failure"] = "Failure inference"
        return result

    if include_image_size:
        result["width"] = image.width
        result["height"] = image.height

    return result


def load_image(input_file, ignore_exif_rotation=False):
    image = open_image(input_file, ignore_exif_rotation=ignore_exif_rotation)
    image.load()
    return image


def open_image(input_file, ignore_exif_rotation=False):

    if isinstance(input_file, str) and input_file.startswith(("http://", "https://")):
        try:
            response = requests.get(input_file)
        except Exception as e:
            print(f"Error retrieving image {input_file}: {e}")
            success = False
            if e.__class__.__name__ in ["ConnectionError"]:
                for i_retry in range(0, 10):
                    try:
                        time.sleep(0.01)
                        response = requests.get(input_file)
                    except Exception as e:
                        print(
                            f"Error retrieving image {input_file} on retry {i_retry}: {e}"
                        )
                        continue
                    print(f"Succeeded on retry {i_retry}")
                    success = True
                    break
            if not success:
                raise
        try:
            image = Image.open(BytesIO(response.content))
        except Exception as e:
            print(f"Error opening image {input_file}: {e}")
            raise

    else:
        image = Image.open(input_file)

    # Convert to RGB if necessary
    if image.mode not in ("RGBA", "RGB", "L", "I;16"):
        raise AttributeError(f"Image {input_file} uses unsupported mode {image.mode}")
    if image.mode == "RGBA" or image.mode == "L":
        # PIL.Image.convert() returns a converted copy of this image
        image = image.convert(mode="RGB")

    if not ignore_exif_rotation:
        try:
            exif = image._getexif()
            orientation: int = exif.get(274, None)
            if (orientation is not None) and (orientation != 1):
                assert orientation in {
                    3: 180,
                    6: 270,
                    8: 90,
                }, "Mirrored rotations are not supported"
                image = image.rotate({3: 180, 6: 270, 8: 90}[orientation], expand=True)
        except Exception:
            pass

    return image
