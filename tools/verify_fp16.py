"""
Decide whether fp16 is safe for the detector: run the SAME real images through
the fp32 ONNX detector and an fp16 version, compare detection counts (recall)
and confidences (accuracy) at the app's operating threshold.

Run from repo root:
    venv\\Scripts\\python.exe tools\\verify_fp16.py [sample_dir] [conf]
"""
import os
import sys
import glob
import gc

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from PIL import Image

from load_detector import load_detector

SAMPLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\WildCatcher\sample_footage"
CONF = float(sys.argv[2]) if len(sys.argv) > 2 else 0.4
FP32 = os.path.join(_ROOT, "detector_AI_model.onnx")
FP16 = os.path.join(_ROOT, "detector_AI_model_fp16.onnx")


def make_fp16():
    import onnx
    from onnxconverter_common import float16
    m = onnx.load(FP32)
    m16 = float16.convert_float_to_float16(m, keep_io_types=True)
    onnx.save(m16, FP16)
    print(f"fp32 size = {os.path.getsize(FP32)/1e6:.0f} MB  ->  "
          f"fp16 size = {os.path.getsize(FP16)/1e6:.0f} MB")


def run(onnx_path, images):
    det = load_detector(onnx_path)
    print(f"  provider: {det.provider}")
    out = {}
    for p in images:
        img = Image.open(p).convert("RGB")
        r = det.generate_detections_one_image(img, os.path.basename(p),
                                              detection_threshold=CONF)
        out[os.path.basename(p)] = r["detections"]
    del det
    gc.collect()
    return out


def main():
    images = sorted(glob.glob(os.path.join(SAMPLE, "*.jpg")) +
                    glob.glob(os.path.join(SAMPLE, "*.jpeg")) +
                    glob.glob(os.path.join(SAMPLE, "*.png")))
    print(f"{len(images)} images @ conf>={CONF}")
    print("=" * 64)
    make_fp16()
    print("--- fp32 ---")
    r32 = run(FP32, images)
    print("--- fp16 ---")
    r16 = run(FP16, images)

    t32 = sum(len(v) for v in r32.values())
    t16 = sum(len(v) for v in r16.values())
    count_mism = 0
    cat_mism = 0
    max_conf_diff = 0.0
    for name in r32:
        a = sorted(r32[name], key=lambda d: -d["conf"])
        b = sorted(r16[name], key=lambda d: -d["conf"])
        if len(a) != len(b):
            count_mism += 1
            print(f"  COUNT DIFF {name}: fp32={len(a)} fp16={len(b)}")
        for da, db in zip(a, b):
            max_conf_diff = max(max_conf_diff, abs(da["conf"] - db["conf"]))
            if da["category"] != db["category"]:
                cat_mism += 1
    print("=" * 64)
    print(f"total detections : fp32={t32}  fp16={t16}")
    print(f"images w/ count mismatch : {count_mism}/{len(r32)}")
    print(f"category mismatches      : {cat_mism}")
    print(f"max confidence diff      : {max_conf_diff:.4f}")
    verdict = (count_mism == 0 and cat_mism == 0 and max_conf_diff < 0.02)
    print("VERDICT:", "fp16 SAFE (no recall/accuracy loss)" if verdict
          else "fp16 changes results -> keep fp32")


if __name__ == "__main__":
    main()
