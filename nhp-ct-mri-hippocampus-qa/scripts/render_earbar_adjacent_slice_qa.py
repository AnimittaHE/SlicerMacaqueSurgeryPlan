#!/usr/bin/env python3
"""Render adjacent native-MRI I/J/K planes around ear-axis search seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nrrd
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mri", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--radius-voxels", type=int, default=21)
    parser.add_argument("--offset-voxels", type=int, default=3)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crop(image: np.ndarray, center_xy: tuple[float, float], radius: int):
    x, y = [int(round(v)) for v in center_xy]
    x0, x1 = max(0, x - radius), min(image.shape[1], x + radius + 1)
    y0, y1 = max(0, y - radius), min(image.shape[0], y + radius + 1)
    return image[y0:y1, x0:x1], x - x0, y - y0


def draw(axis, image, center_xy, limits, radius, title):
    patch, cx, cy = crop(image, center_xy, radius)
    axis.imshow(patch, cmap="gray", origin="lower", vmin=limits[0], vmax=limits[1])
    axis.axvline(cx, color="#ff3030", lw=1.1)
    axis.axhline(cy, color="#ff3030", lw=1.1)
    axis.set_title(title, fontsize=8)
    axis.set_xticks([])
    axis.set_yticks([])


def main() -> None:
    args = parse_args()
    mri, header = nrrd.read(str(args.mri))
    if mri.ndim != 3:
        raise ValueError(f"Expected 3D MRI; got shape {mri.shape}")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("status") != "UNVERIFIED_TEMPLATE_SEARCH_SEEDS_NOT_ACCEPTED_FOR_SURGERY":
        raise ValueError("report status is not an ear-axis search-seed report")
    recorded_hash = str(report.get("mri_sha256", ""))
    if recorded_hash.casefold() != sha256(args.mri).casefold():
        raise ValueError("the supplied MRI does not match the report MRI SHA256")
    recorded_path = Path(str(report.get("mri", "")))
    if str(recorded_path.resolve()).casefold() != str(args.mri.resolve()).casefold():
        raise ValueError("the supplied MRI path does not match the report")
    candidates = report.get("candidate_points", [])
    if len(candidates) != 2:
        raise ValueError("Report must contain exactly two candidate_points")

    directions = np.asarray(header["space directions"], dtype=float).T
    spacing = np.linalg.norm(directions, axis=0)
    finite = mri[np.isfinite(mri)]
    limits = tuple(np.percentile(finite, [2, 99.5]))
    offsets = (-args.offset_voxels, 0, args.offset_voxels)

    fig, axes = plt.subplots(2, 9, figsize=(23, 6.2), facecolor="white")
    for row, candidate in enumerate(candidates):
        i, j, k = candidate["subject_ijk_continuous"]
        ii, jj, kk = [int(round(v)) for v in (i, j, k)]
        for col, delta in enumerate(offsets):
            sk = int(np.clip(kk + delta, 0, mri.shape[2] - 1))
            draw(
                axes[row, col],
                mri[:, :, sk].T,
                (i, j),
                limits,
                args.radius_voxels,
                f"K-plane offset {delta * spacing[2]:+.1f} mm",
            )
        for col, delta in enumerate(offsets):
            sj = int(np.clip(jj + delta, 0, mri.shape[1] - 1))
            draw(
                axes[row, 3 + col],
                mri[:, sj, :].T,
                (i, k),
                limits,
                args.radius_voxels,
                f"J-plane offset {delta * spacing[1]:+.1f} mm",
            )
        for col, delta in enumerate(offsets):
            si = int(np.clip(ii + delta, 0, mri.shape[0] - 1))
            draw(
                axes[row, 6 + col],
                mri[si, :, :].T,
                (j, k),
                limits,
                args.radius_voxels,
                f"I-plane offset {delta * spacing[0]:+.1f} mm",
            )
        axes[row, 0].set_ylabel(
            f"{candidate['name']}\nIJK {np.round([i, j, k], 2)}", fontsize=9
        )

    fig.suptitle(
        "Native MRI voxel-index planes: template ear-axis search seeds\n"
        "UNVERIFIED research candidates - planes are not anatomical labels for oblique data",
        fontsize=14,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=190)
    plt.close(fig)
    print(f"Wrote QA image: {args.output}")


if __name__ == "__main__":
    main()
