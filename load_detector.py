import time
import torch
CONF_DIGITS = 3
COORD_DIGITS = 4

def load_detector(model_file, force_cpu=False, force_model_download=False):

    start_time = time.time()
    if model_file.endswith(".pt"):

        detector = PTDetector(model_file, force_cpu, False)
    else:
        raise ValueError("Unrecognized model format: {}".format(model_file))
    elapsed = time.time() - start_time
    print("Loaded model in ", elapsed, " seconds")

    return detector


import numpy as np
import traceback
from yolov5.utils.augmentations import letterbox
from yolov5.utils.general import non_max_suppression, xyxy2xywh
from yolov5.utils.general import scale_boxes as scale_coords

class PTDetector:
    IMAGE_SIZE = 1280
    STRIDE = 64

    def __init__(self, model_path, force_cpu=False, use_model_native_classes=False):

        self.device = 'cpu'
        if not force_cpu:
            if torch.cuda.is_available():
                self.device = torch.device('cuda:0')
            try:
                if torch.backends.mps.is_built and torch.backends.mps.is_available():
                    self.device = 'mps'
            except AttributeError:
                pass

        try:
            self.model = PTDetector._load_model(model_path, self.device)
            if self.device != 'cpu':
                print('Sending model to GPU')
                self.model.to(self.device)
                # Force a kernel launch to verify GPU actually works
                torch.zeros(1, device=self.device).sum()
        except RuntimeError as e:
            if self.device != 'cpu':
                print(f'GPU failed: {e}')
                print('Falling back to CPU — processing will be slower.')
                self.device = 'cpu'
                self.model = PTDetector._load_model(model_path, self.device)
            else:
                raise

        self.printed_image_size_warning = False
        self.use_model_native_classes = use_model_native_classes
        

    @staticmethod
    def _load_model(model_pt_path, device):

        use_map_location = (device != 'mps')        
        
        if use_map_location:
            checkpoint = torch.load(model_pt_path, map_location=device, weights_only=False)
        else:
            checkpoint = torch.load(model_pt_path, weights_only=False)

        for m in checkpoint['model'].modules():
            t = type(m)
            if t is torch.nn.Upsample and not hasattr(m, 'recompute_scale_factor'):
                m.recompute_scale_factor = None
        
        if use_map_location:
            model = checkpoint['model'].float().fuse().eval()
        else:
            model = checkpoint['model'].float().fuse().eval().to(device)
            
        return model

    def generate_detections_one_image(self, 
                                      img_original, 
                                      image_id='unknown', 
                                      detection_threshold=0.00001, 
                                      image_size=None,
                                      skip_image_resizing=False,
                                      augment=False):

        result = {'file': image_id }
        detections = []
        max_conf = 0.0

        if detection_threshold is None:
            
            detection_threshold = 0
            
        try:
            
            if not isinstance(img_original,np.ndarray):                
                img_original = np.asarray(img_original)

            # Padded resize
            target_size = PTDetector.IMAGE_SIZE
            
            # Image size can be an int (which translates to a square target size) or (h,w)
            if image_size is not None:
                
                assert isinstance(image_size,int) or (len(image_size)==2)
                
                if not self.printed_image_size_warning:
                    print('Warning: using user-supplied image size {}'.format(image_size))
                    self.printed_image_size_warning = True
            
                target_size = image_size
            
            else:
                
                self.printed_image_size_warning = False
                
            # ...if the caller has specified an image size
            
            if skip_image_resizing:
                img = img_original
            else:
                letterbox_result = letterbox(img_original, 
                                             new_shape=target_size,
                                             stride=PTDetector.STRIDE, 
                                             auto=True)
                img = letterbox_result[0]                
            
            # HWC to CHW; PIL Image is RGB already
            img = img.transpose((2, 0, 1))
            img = np.ascontiguousarray(img)
            img = torch.from_numpy(img)
            img = img.to(self.device)
            img = img.float()
            img /= 255

            # In practice this is always true 
            if len(img.shape) == 3:  
                img = torch.unsqueeze(img, 0)

            pred = self.model(img,augment=augment)[0]

            # NMS
            if self.device == 'mps':

                pred = non_max_suppression(prediction=pred.cpu(), conf_thres=detection_threshold)
            else: 
                pred = non_max_suppression(prediction=pred, conf_thres=detection_threshold)


            gn = torch.tensor(img_original.shape)[[1, 0, 1, 0]]

            for det in pred:
                
                if len(det):
                    
                    # Rescale boxes from img_size to im0 size
                    det[:, :4] = scale_coords(img.shape[2:], det[:, :4], img_original.shape).round()

                    for *xyxy, conf, cls in reversed(det):
                        
                        # normalized center-x, center-y, width and height
                        xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()

                        api_box = convert_yolo_to_xywh(xywh)

                        conf = truncate_float(conf.tolist(), precision=CONF_DIGITS)

                        if not self.use_model_native_classes:

                            cls = int(cls.tolist()) + 1
                            if cls not in (1, 2, 3):
                                raise KeyError(f'{cls} is not a valid class.')
                        else:
                            cls = int(cls.tolist())

                        detections.append({
                            'category': str(cls),
                            'conf': conf,
                            'bbox': truncate_float_array(api_box, precision=COORD_DIGITS)
                        })
                        max_conf = max(max_conf, conf)

        
        except Exception as e:
            
            result['failure'] = 'Failure inference'
            print('PTDetector: image {} failed during inference: {}\n'.format(image_id, str(e)))
            traceback.print_exc(e)

        result['max_detection_conf'] = max_conf
        result['detections'] = detections

        return result


import math
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
