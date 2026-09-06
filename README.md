# SlicerMacaqueSurgeryPlan

Research-only Codex Skill for non-human-primate CT-to-T1 MRI registration, hippocampal visualization, cranial landmarks, candidate-frame QA, and smooth skull-curvature models using 3D Slicer, Blender Boolean operations and STEP solids.

> [!CAUTION]
> This project does not approve surgery, define a craniotomy, select a trajectory or target, establish a safety margin, or replace review by qualified veterinary, neurosurgical, imaging, and stereotactic-frame specialists.

## What it supports

- CT-to-T1 MRI registration with orientation, laterality, transform-direction, and double-transform checks.
- Multi-start registration review and independent landmark target-registration-error (TRE) measurement.
- Atlas-based or manually reviewed bilateral hippocampal-formation candidates.
- CT-derived inferior orbital-rim (orbitale) candidates with adjacent-slice and 3D bone QA.
- Expert-marked bony external-auditory-meatus (EAM) candidates.
- Calibrated mechanical ear-bar contact candidates.
- Template-derived ear-region search seeds for visualization only.
- Interaural/Ear-Bar Zero (EBZ) midpoint and candidate AP/ML/DV frame construction.
- User-defined rectangular models derived from the scene's existing smooth skull using Blender Exact Boolean intersection and inner-wall extraction.
- Compact continuous curved bottoms, planar tops and user-specified minimum axial thickness, exported as ordinary STEP solids for further CAD development.
- 3D Slicer scene packaging, provenance records, hashes, and static MRML auditing.

## EBZ terminology

Ear-Bar Zero is an apparatus-defined stereotactic reference, not a universal anatomical point. A CT/MRI-derived interaural midpoint is only a research candidate. Mechanical EBZ requires subject-specific evidence for the actual bilateral ear-bar contacts, apparatus calibration, verified head positioning, and expert review.

## Model generation with Blender

Use the selected scene's existing smooth Skull surface and the user's rectangle, axis and in-plane reference. Preserve its registered world coordinates, export the skull and crossing prism together, and execute an Exact Boolean INTERSECT in Blender. Extract the cavity-facing inner wall and fit broad curvature with a compact bicubic surface, initially 16 control points. Keep case coordinates and subject paths outside this repository.

For minimum axial thickness t, set the flat top to the continuous bottom's maximum height plus t. Preserve the bottom when changing thickness. Sew the bottom, top and four sides into a BREP solid and verify STEP and Slicer scene reloads. See [the modeling workflow](nhp-ct-mri-hippocampus-qa/references/skull-blender-modeling.md) for coordinate handling, fitting, extrema, CAD export and validation. Inner skull curvature is not a segmented cortex. This branch is agent-guided; the retained MRI-mask script is a legacy method, not an end-to-end Blender runner.

## Repository layout

The installable Codex Skill is in [`nhp-ct-mri-hippocampus-qa/`](nhp-ct-mri-hippocampus-qa/):

```text
nhp-ct-mri-hippocampus-qa/
├── SKILL.md
├── agents/
├── assets/
├── references/
└── scripts/
```

This repository contains a Codex Skill that guides and validates a 3D Slicer workflow. It is not a compiled 3D Slicer extension.

## Installation

1. Clone this repository.
2. Copy the complete `nhp-ct-mri-hippocampus-qa` folder into your Codex skills directory.
3. Restart or reload Codex so the skill can be discovered.
4. Invoke it with:

```text
$nhp-ct-mri-hippocampus-qa
```

## Core safeguards

- Preserve source imaging files byte-for-byte and write only to derivative directories.
- Keep T1 MRI fixed and apply the chosen CT-to-MRI transform exactly once.
- Never infer biological laterality from screen position or registration alone.
- Keep bony EAM landmarks, mechanical ear-bar contacts, and template search seeds distinct.
- Require the contact footprint and projection direction to come from the user or a documented expert-reviewed planning step; the Skill does not choose a craniotomy or trajectory.
- Treat brain-mask smoothing and artificial-dura offsets as unverified geometry parameters, not tissue-mechanics or pressure models.
- Treat every image, segmentation, point, midpoint, line, plane, and axis as a research candidate until the required QA and named expert review are complete.
- Never reuse subject-specific transforms, indices, thresholds, search regions, side mappings, or apparatus calibration records.

See [`SKILL.md`](nhp-ct-mri-hippocampus-qa/SKILL.md) for the complete gated workflow and resource routing.

## License

This project is released under the [MIT License](LICENSE).
