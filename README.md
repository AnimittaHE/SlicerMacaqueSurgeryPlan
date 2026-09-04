# SlicerMacaqueSurgeryPlan

Research-only Codex Skill for guarded non-human-primate CT-to-T1 MRI registration, hippocampal-formation candidate visualization, cranial-landmark localization, stereotactic-frame candidate QA, and MRI-derived brain-contact curvature candidate modeling in 3D Slicer.

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
- User-defined directed rectangular brain-surface contact candidates, including an open contact surface and watertight CAD intermediary block.
- Configurable outer-envelope and Gaussian smoothing for artificial-dura concept studies, with an explicit non-negative offset and no-penetration clamp.
- 3D Slicer scene packaging, provenance records, hashes, and static MRML auditing.

## EBZ terminology

Ear-Bar Zero is an apparatus-defined stereotactic reference, not a universal anatomical point. A CT/MRI-derived interaural midpoint is only a research candidate. Mechanical EBZ requires subject-specific evidence for the actual bilateral ear-bar contacts, apparatus calibration, verified head positioning, and expert review.

## Brain-contact geometry branch

Copy [`brain-contact-config.example.json`](nhp-ct-mri-hippocampus-qa/assets/brain-contact-config.example.json) into a new derivative case directory and enter the two opposite rectangle corners, the directed projection line, the in-plane reference vector, and the frozen MRI-space brain-mask path. Keep case coordinates and subject paths outside this repository.

Run [`slicer_generate_brain_contact_block.py`](nhp-ct-mri-hippocampus-qa/scripts/slicer_generate_brain_contact_block.py) in 3D Slicer with `NHP_BRAIN_CONTACT_CONFIG` set to that completed configuration. The script produces an open contact-surface STL, a watertight closed-block STL, input markups, deterministic raw/intermediate/final depth maps, mesh/reload QA, provenance, and hashes. See [`brain-surface-contact-modeling.md`](nhp-ct-mri-hippocampus-qa/references/brain-surface-contact-modeling.md) for inputs, invariants, stop conditions, and artificial-dura limitations.

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
