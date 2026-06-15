"""
Integration test for the customizable export engine: run a few real images
through process_image_file, then export ALL formats with a custom field set
and verify the outputs. Operates on a temp copy so sample_footage is untouched.

Run from repo root:
    venv\\Scripts\\python.exe tools\\test_output.py
"""
import os
import sys
import glob
import json
import shutil
import sqlite3
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

import wc_output
import wc_models
from load_detector import load_detector
from wc_processing import process_image_file

SRC = r"C:\WildCatcher\sample_footage"
DET_PER_CLASS = {"animal": {"include": True}, "human": {"include": True},
                 "empty": {"include": False}}


def main():
    work = tempfile.mkdtemp(prefix="wc_test_")
    in_dir = os.path.join(work, "in")
    out_dir = os.path.join(work, "in", "detection_data")
    os.makedirs(out_dir, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(SRC, "*.jpg")))[:5]:
        shutil.copy2(p, in_dir)

    det = load_detector(os.path.join(_ROOT, "detector_AI_model.onnx"))
    clf = wc_models.get_model_entry("4type_classifier")
    clf_steps = [{"model_id": "4type_classifier", "per_class": {}}] if clf else None

    records = []
    for i, p in enumerate(sorted(glob.glob(os.path.join(in_dir, "*.jpg"))), start=1):
        fs = process_image_file(p, det, 0.4, DET_PER_CLASS, out_dir,
                                log=lambda m: None, classifier_steps=clf_steps)
        d = fs.get("detail")
        if d:
            d["id"] = i
            records.append(d)

    print(f"processed {len(records)} files")
    print("sample record keys:", sorted(records[0].keys()) if records else "none")

    fields = ["id", "file_name", "file_type", "time", "detection",
              "total_detections", "animal_count", "species", "species_counts",
              "detection_accuracy", "image_width", "image_height", "camera_make"]
    summary = {"total_files": len(records), "total_empty": 0,
               "total_human": 0, "total_animal": len(records), "species_counts": {}}
    written = wc_output.write_reports(records, out_dir, fields=fields,
                                      formats=wc_output.ALL_FORMATS,
                                      summary=summary, log=print)
    print("written:", [os.path.basename(w) for w in written])

    # --- verify each format ---
    base = os.path.join(out_dir, wc_output.REPORT_BASENAME)
    with open(base + ".csv", encoding="utf-8-sig") as f:
        print("CSV header:", f.readline().strip())
    with open(base + ".json", encoding="utf-8") as f:
        j = json.load(f)
        print(f"JSON records: {len(j)}; first keys: {list(j[0].keys()) if j else []}")
    con = sqlite3.connect(base + ".db")
    n = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    print(f"SQLite rows: {n}")
    con.close()
    tdb, ddb = base + ".tdb", base + ".ddb"
    print(f"Timelapse .tdb exists: {os.path.exists(tdb)}  .ddb exists: {os.path.exists(ddb)}")
    con = sqlite3.connect(ddb)
    dt = con.execute("SELECT COUNT(*) FROM DataTable").fetchone()[0]
    cols = [r[1] for r in con.execute("PRAGMA table_info(DataTable)").fetchall()]
    print(f"Timelapse DataTable rows: {dt}; columns: {cols}")
    con.close()
    print("xlsx exists:", os.path.exists(base + ".xlsx"))

    shutil.rmtree(work, ignore_errors=True)
    print("OK")


if __name__ == "__main__":
    main()
