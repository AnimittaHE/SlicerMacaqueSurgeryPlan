#!/usr/bin/env python3
"""Check an Analyze/NIfTI pair without guessing orientation."""

import argparse
import json
import math
import struct
import sys
from pathlib import Path


def paired_paths(path):
    suffix = path.suffix.lower()
    if suffix not in (".img", ".hdr"):
        raise ValueError("input must end in .img or .hdr")
    stem = path.with_suffix("")
    return stem.with_suffix(".img"), stem.with_suffix(".hdr")


def parse_header(hdr_path):
    data = hdr_path.read_bytes()
    if len(data) < 348:
        raise ValueError(f"header is shorter than 348 bytes: {len(data)}")
    endian = None
    for candidate in ("<", ">"):
        if struct.unpack_from(candidate + "i", data, 0)[0] == 348:
            endian = candidate
            break
    if endian is None:
        raise ValueError("sizeof_hdr is not 348 in little- or big-endian form")
    dim = struct.unpack_from(endian + "8h", data, 40)
    ndim = int(dim[0])
    if ndim < 1 or ndim > 7:
        raise ValueError(f"invalid dimension count: {ndim}")
    shape = [int(value) for value in dim[1 : ndim + 1]]
    if any(value <= 0 for value in shape):
        raise ValueError(f"invalid shape: {shape}")
    datatype = int(struct.unpack_from(endian + "h", data, 70)[0])
    bitpix = int(struct.unpack_from(endian + "h", data, 72)[0])
    pixdim = [float(value) for value in struct.unpack_from(endian + "8f", data, 76)]
    zooms = pixdim[1 : ndim + 1]
    if any(not math.isfinite(value) or value <= 0 for value in zooms):
        raise ValueError(f"invalid voxel sizes: {zooms}")
    vox_offset = float(struct.unpack_from(endian + "f", data, 108)[0])
    return {
        "endianness": "little" if endian == "<" else "big",
        "shape": shape,
        "datatype_code": datatype,
        "bitpix": bitpix,
        "voxel_sizes": zooms,
        "vox_offset": vox_offset,
    }


def nibabel_details(img_path):
    try:
        import nibabel as nib
        import numpy as np
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    image = nib.load(str(img_path))
    affine = np.asarray(image.affine, dtype=float)
    details = {
        "available": True,
        "image_class": type(image).__name__,
        "header_class": type(image.header).__name__,
        "shape": list(image.shape),
        "zooms": [float(value) for value in image.header.get_zooms()],
        "affine": affine.tolist(),
        "affine_determinant_3x3": float(np.linalg.det(affine[:3, :3])),
        "axis_codes": list(nib.aff2axcodes(affine)),
    }
    if hasattr(image, "get_qform"):
        qform, qcode = image.get_qform(coded=True)
        sform, scode = image.get_sform(coded=True)
        details["qform_code"] = int(qcode or 0)
        details["sform_code"] = int(scode or 0)
        if qform is not None and sform is not None:
            details["qform_sform_max_abs_difference"] = float(np.max(np.abs(qform - sform)))
    return details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--report")
    parser.add_argument("--ambiguous-exit-zero", action="store_true")
    args = parser.parse_args()
    report = {"status": "FAIL", "orientation_status": "UNKNOWN", "errors": [], "warnings": []}
    try:
        img_path, hdr_path = paired_paths(Path(args.path))
        missing = [str(path) for path in (img_path, hdr_path) if not path.exists()]
        if missing:
            raise FileNotFoundError(f"missing paired file(s): {missing}")
        header = parse_header(hdr_path)
        expected_bytes = math.prod(header["shape"]) * max(header["bitpix"], 0) // 8
        actual_bytes = img_path.stat().st_size
        if expected_bytes and actual_bytes < expected_bytes:
            raise ValueError(f"image file is too small: expected >= {expected_bytes}, got {actual_bytes}")
        nib = nibabel_details(img_path)
        report.update(
            {
                "status": "STRUCTURAL_PAIR_PASS_ORIENTATION_REVIEW_REQUIRED",
                "img": str(img_path.resolve()),
                "hdr": str(hdr_path.resolve()),
                "img_size_bytes": actual_bytes,
                "header": header,
                "nibabel": nib,
                "orientation_status": "AMBIGUOUS_REQUIRES_EXTERNAL_CONFIRMATION",
            }
        )
        if nib.get("available") and nib.get("image_class") == "Nifti1Pair":
            difference = nib.get("qform_sform_max_abs_difference")
            if difference is not None and difference > 1e-4:
                report["warnings"].append("qform and sform materially differ")
            else:
                report["orientation_status"] = "HEADER_AFFINE_AVAILABLE_REVIEW_REQUIRED"
        else:
            report["warnings"].append(
                "Analyze geometry does not reliably establish biological orientation; do not guess dimensions, axes, or left/right"
            )
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    if report["status"] == "FAIL":
        return 2
    if report["orientation_status"].startswith("AMBIGUOUS") and not args.ambiguous_exit_zero:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
