# SlicerMacaqueSurgeryPlan

Research-only Codex Skill for guarded non-human-primate CT-to-T1 MRI registration, hippocampal-formation candidate visualization, cranial-landmark localization, and stereotactic-frame candidate QA in 3D Slicer.

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
- 3D Slicer scene packaging, provenance records, hashes, and static MRML auditing.

## EBZ terminology

Ear-Bar Zero is an apparatus-defined stereotactic reference, not a universal anatomical point. A CT/MRI-derived interaural midpoint is only a research candidate. Mechanical EBZ requires subject-specific evidence for the actual bilateral ear-bar contacts, apparatus calibration, verified head positioning, and expert review.

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
- Treat every image, segmentation, point, midpoint, line, plane, and axis as a research candidate until the required QA and named expert review are complete.
- Never reuse subject-specific transforms, indices, thresholds, search regions, side mappings, or apparatus calibration records.

See [`SKILL.md`](nhp-ct-mri-hippocampus-qa/SKILL.md) for the complete gated workflow and resource routing.
