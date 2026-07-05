"""ONNX-backed YOLOv5 detector for WildCatcher.

Drop-in replacement for the former PyTorch PTDetector: same `load_detector()`
entry point and the same `generate_detections_one_image(...)` interface and
output dict, so process_images.py / wc_processing.py are unchanged. Inference
runs on ONNX Runtime (GPU via DirectML/CoreML/CUDA) with no torch at runtime.
"""
import time
import math

import numpy as np

from wc_onnx import create_session
from wc_yolo_utils import letterbox, non_max_suppression, scale_boxes, xyxy2xywh

CONF_DIGITS = 3
COORD_DIGITS = 4


def load_detector(model_file, force_cpu=False, force_model_download=False):
    start_time = time.time()
    if model_file.endswith(".onnx"):
        detector = OnnxDetector(model_file, force_cpu)
    elif model_file.endswith(".pt"):
        raise ValueError(
            "Detector must be an .onnx model now. Convert the .pt once with "
            "tools/convert_to_onnx.py."
        )
    else:
        raise ValueError("Unrecognized model format: {}".format(model_file))
    print("Loaded model in ", time.time() - start_time, " seconds")
    return detector


class OnnxDetector:
    IMAGE_SIZE = 1280
    STRIDE = 64

    def __init__(self, model_path, force_cpu=False, use_model_native_classes=False):
        self.session, self.provider = create_session(model_path, prefer_gpu=not force_cpu)
        self.input_name = self.session.get_inputs()[0].name
        self.printed_image_size_warning = False
        self.use_model_native_classes = use_model_native_classes
        print(f"Detector running on: {self.provider}")

    def generate_detections_one_image(self,
                                      img_original,
                                      image_id='unknown',
                                      detection_threshold=0.00001,
                                      image_size=None,
                                      skip_image_resizing=False,
                                      augment=False):
        result = {'file': image_id}
        detections = []
        max_conf = 0.0

        if detection_threshold is None:
            detection_threshold = 0

        try:
            if not isinstance(img_original, np.ndarray):
                img_original = np.asarray(img_original)

            target_size = OnnxDetector.IMAGE_SIZE
            if image_size is not None:
                assert isinstance(image_size, int) or (len(image_size) == 2)
                if not self.printed_image_size_warning:
                    print('Warning: using user-supplied image size {}'.format(image_size))
                    self.printed_image_size_warning = True
                target_size = image_size
            else:
                self.printed_image_size_warning = False

            # Padded resize (letterbox keeps aspect ratio; auto=True -> rectangular)
            if skip_image_resizing:
                img = img_original
            else:
                img = letterbox(img_original, new_shape=target_size,
                                stride=OnnxDetector.STRIDE, auto=True)[0]

            # HWC -> CHW; PIL/np image is RGB already
            img = img.transpose((2, 0, 1))
            img = np.ascontiguousarray(img).astype(np.float32)
            img /= 255.0
            if img.ndim == 3:
                img = img[None]  # add batch dim

            pred = self.session.run(None, {self.input_name: img})[0]
            pred = non_max_suppression(pred, conf_thres=detection_threshold)

            for det in pred:
                dets, mc = self._extract(det, img.shape[2:], img_original.shape)
                detections.extend(dets)
                max_conf = max(max_conf, mc)

        except Exception as e:
            result['failure'] = 'Failure inference'
            print('OnnxDetector: image {} failed during inference: {}\n'.format(image_id, str(e)))

        result['max_detection_conf'] = max_conf
        result['detections'] = detections
        return result

    def _extract(self, det, input_hw, orig_shape):
        """Scale + format the boxes for one image. Shared by the single and
        batch paths so their outputs are byte-for-byte identical."""
        detections = []
        max_conf = 0.0
        h0, w0 = orig_shape[0], orig_shape[1]
        gn = np.array([w0, h0, w0, h0], dtype=np.float32)  # normalization gain
        if len(det):
            det[:, :4] = scale_boxes(input_hw, det[:, :4], orig_shape).round()
            for row in det[::-1]:  # reversed, matching previous behavior
                xyxy = row[:4]
                conf = float(row[4])
                cls = int(row[5])

                xywh = (xyxy2xywh(xyxy.reshape(1, 4)) / gn).reshape(-1).tolist()
                api_box = convert_yolo_to_xywh(xywh)
                conf = truncate_float(conf, precision=CONF_DIGITS)

                if not self.use_model_native_classes:
                    cls = cls + 1
                    if cls not in (1, 2, 3):
                        raise KeyError(f'{cls} is not a valid class.')

                detections.append({
                    'category': str(cls),
                    'conf': conf,
                    'bbox': truncate_float_array(api_box, precision=COORD_DIGITS),
                })
                max_conf = max(max_conf, conf)
        return detections, max_conf

    def generate_detections_batch(self, images, image_ids=None,
                                  detection_threshold=0.00001):
        """Run a batch of images that letterbox to the SAME shape through the
        detector in one session call. Returns a list of per-image result dicts
        identical to generate_detections_one_image (verified by parity test).

        The caller MUST group images by original size so their letterboxed
        tensors stack — this preserves each image's exact rectangular letterbox
        (auto=True), so results are identical to the per-image path.
        """
        if detection_threshold is None:
            detection_threshold = 0
        np_images = [im if isinstance(im, np.ndarray) else np.asarray(im)
                     for im in images]
        ids = image_ids or ['unknown'] * len(np_images)
        results = [{'file': ids[i], 'detections': [], 'max_detection_conf': 0.0}
                   for i in range(len(np_images))]
        if not np_images:
            return results
        try:
            target_size = OnnxDetector.IMAGE_SIZE
            batch = [letterbox(im, new_shape=target_size,
                               stride=OnnxDetector.STRIDE, auto=True)[0].transpose((2, 0, 1))
                     for im in np_images]
            inp = np.ascontiguousarray(np.stack(batch)).astype(np.float32)
            inp /= 255.0
            pred = self.session.run(None, {self.input_name: inp})[0]
            preds = non_max_suppression(pred, conf_thres=detection_threshold)
            for i, det in enumerate(preds):
                dets, mc = self._extract(det, inp.shape[2:], np_images[i].shape)
                results[i]['detections'] = dets
                results[i]['max_detection_conf'] = mc
        except Exception as e:
            print('OnnxDetector: batch failed during inference: {}'.format(str(e)))
            for r in results:
                r['failure'] = 'Failure inference'
        return results


def convert_yolo_to_xywh(yolo_box):
    x_center, y_center, width_of_box, height_of_box = yolo_box
    x_min = x_center - width_of_box / 2.0
    y_min = y_center - height_of_box / 2.0
    return [x_min, y_min, width_of_box, height_of_box]


def truncate_float_array(xs, precision=3):
    return [truncate_float(x, precision=precision) for x in xs]


def truncate_float(x, precision=3):
    """Truncate a float to a given precision without rounding."""
    assert precision > 0
    if np.isclose(x, 0):
        return 0
    elif x > 1:
        fractional_component = x - 1.0
        return 1 + truncate_float(fractional_component, precision)
    else:
        factor = math.pow(10, precision - 1 - math.floor(math.log10(abs(x))))
        return math.floor(x * factor) / factor
