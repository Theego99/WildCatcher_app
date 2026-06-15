"""
End-to-end check on real footage: detector -> crop -> classifier, all on ONNX.
Confirms the migrated pipeline produces sensible detections + classifications
on real images and that the GPU (DirectML) is used.

Run from repo root:
    venv\\Scripts\\python.exe tools\\verify_pipeline.py [sample_dir]
"""
import os
import sys
import glob
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from PIL import Image

from load_detector import load_detector
import wc_models

SAMPLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\WildCatcher\sample_footage"
DET_CONF = 0.4
CLASSIFIER_ID = "4type_classifier"  # bear / boar / deer / rest


def main():
    images = sorted(glob.glob(os.path.join(SAMPLE, "*.jpg")) +
                    glob.glob(os.path.join(SAMPLE, "*.jpeg")) +
                    glob.glob(os.path.join(SAMPLE, "*.png")))
    det = load_detector(os.path.join(_ROOT, "detector_AI_model.onnx"))
    clf_entry = wc_models.get_model_entry(CLASSIFIER_ID)
    print(f"detector provider : {det.provider}")
    if clf_entry:
        wc_models.load_classifier(clf_entry)  # warm + report provider
    print("=" * 70)

    n_imgs = n_animal = n_human = 0
    tmp = os.path.join(tempfile.gettempdir(), "_wc_crop.png")
    for p in images:
        img = Image.open(p).convert("RGB")
        W, H = img.size
        r = det.generate_detections_one_image(img, os.path.basename(p),
                                              detection_threshold=DET_CONF)
        dets = r["detections"]
        n_imgs += 1
        labels = []
        for d in dets:
            cat = d["category"]
            if cat == "1":
                n_animal += 1
            else:
                n_human += 1
            line = f"{ {'1':'animal','2':'person','3':'vehicle'}.get(cat, cat) }({d['conf']:.2f})"
            # classify animal crops
            if cat == "1" and clf_entry:
                x, y, w, h = d["bbox"]
                box = (int(x * W), int(y * H), int((x + w) * W), int((y + h) * H))
                if box[2] > box[0] and box[3] > box[1]:
                    img.crop(box).save(tmp)
                    species, conf = wc_models.classify_image(tmp, clf_entry)
                    line += f"->{species}({conf:.2f})"
            labels.append(line)
        print(f"{os.path.basename(p)[:40]:<42} {len(dets)} det: {', '.join(labels) if labels else '(none)'}")

    print("=" * 70)
    print(f"images={n_imgs}  animal detections={n_animal}  person/vehicle={n_human}")
    if os.path.exists(tmp):
        os.remove(tmp)


if __name__ == "__main__":
    main()
