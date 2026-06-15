"""
Numpy/OpenCV YOLOv5 pre/post-processing for WildCatcher.

These are torch-free ports of the yolov5 helpers the detector used to import from
`yolov5.utils.*` (letterbox, non_max_suppression, scale_boxes, xyxy2xywh). Porting
them here lets the runtime drop torch, ultralytics, and matplotlib entirely while
keeping detection output numerically equivalent to the previous PyTorch path.
"""
import cv2
import numpy as np


def letterbox(im, new_shape=(640, 640), color=(114, 114, 114), auto=True,
              scaleFill=False, scaleup=True, stride=32):
    """Resize+pad image to a stride-multiple shape. Verbatim from yolov5
    (already numpy/cv2). Returns (img, ratio, (dw, dh))."""
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:  # only scale down, do not scale up (for better val mAP)
        r = min(r, 1.0)

    ratio = r, r
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    if auto:  # minimum rectangle
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)
    elif scaleFill:  # stretch
        dw, dh = 0.0, 0.0
        new_unpad = (new_shape[1], new_shape[0])
        ratio = new_shape[1] / shape[1], new_shape[0] / shape[0]

    dw /= 2
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return im, ratio, (dw, dh)


def xyxy2xywh(x):
    """[x1,y1,x2,y2] -> [xc,yc,w,h]."""
    y = np.copy(x)
    y[..., 0] = (x[..., 0] + x[..., 2]) / 2
    y[..., 1] = (x[..., 1] + x[..., 3]) / 2
    y[..., 2] = x[..., 2] - x[..., 0]
    y[..., 3] = x[..., 3] - x[..., 1]
    return y


def xywh2xyxy(x):
    """[xc,yc,w,h] -> [x1,y1,x2,y2]."""
    y = np.copy(x)
    y[..., 0] = x[..., 0] - x[..., 2] / 2
    y[..., 1] = x[..., 1] - x[..., 3] / 2
    y[..., 2] = x[..., 0] + x[..., 2] / 2
    y[..., 3] = x[..., 1] + x[..., 3] / 2
    return y


def clip_boxes(boxes, shape):
    """Clip xyxy boxes to image shape (h, w), in place."""
    boxes[..., [0, 2]] = boxes[..., [0, 2]].clip(0, shape[1])
    boxes[..., [1, 3]] = boxes[..., [1, 3]].clip(0, shape[0])


def scale_boxes(img1_shape, boxes, img0_shape, ratio_pad=None):
    """Rescale xyxy boxes from img1_shape (network in) to img0_shape (original)."""
    if ratio_pad is None:
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])
        pad = ((img1_shape[1] - img0_shape[1] * gain) / 2,
               (img1_shape[0] - img0_shape[0] * gain) / 2)
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    boxes[..., [0, 2]] -= pad[0]
    boxes[..., [1, 3]] -= pad[1]
    boxes[..., :4] /= gain
    clip_boxes(boxes, img0_shape)
    return boxes


def _nms(boxes, scores, iou_thres):
    """Greedy NMS, returns kept indices in descending-score order."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(iou <= iou_thres)[0] + 1]
    return np.array(keep, dtype=np.int64)


def non_max_suppression(prediction, conf_thres=0.25, iou_thres=0.45, max_det=300):
    """Numpy NMS matching yolov5's default (best-class-only) path.

    prediction: (bs, N, 5+nc) numpy array (post-sigmoid detector output).
    Returns: list of (n, 6) arrays per image [x1, y1, x2, y2, conf, cls].
    """
    if isinstance(prediction, (list, tuple)):
        prediction = prediction[0]
    prediction = np.asarray(prediction, dtype=np.float32)

    bs = prediction.shape[0]
    nc = prediction.shape[2] - 5
    xc = prediction[..., 4] > conf_thres  # candidate boxes by objectness
    max_wh, max_nms = 7680, 30000

    output = [np.zeros((0, 6), dtype=np.float32) for _ in range(bs)]
    for xi in range(bs):
        x = prediction[xi][xc[xi]]
        if not x.shape[0]:
            continue

        x[:, 5:] *= x[:, 4:5]  # conf = obj_conf * cls_conf
        box = xywh2xyxy(x[:, :4])

        cls_scores = x[:, 5:5 + nc]
        j = cls_scores.argmax(1)
        conf = cls_scores[np.arange(cls_scores.shape[0]), j]
        keep = conf > conf_thres
        x = np.concatenate(
            [box[keep], conf[keep, None], j[keep, None].astype(np.float32)], axis=1)

        n = x.shape[0]
        if not n:
            continue
        if n > max_nms:
            x = x[x[:, 4].argsort()[::-1][:max_nms]]

        c = x[:, 5:6] * max_wh  # class-aware offset for batched NMS
        i = _nms(x[:, :4] + c, x[:, 4], iou_thres)[:max_det]
        output[xi] = x[i]

    return output
