---
name: nhp-ct-mri-hippocampus-qa
description: Run a guarded research-only workflow for non-human-primate CT-to-T1 MRI registration, orientation and laterality auditing, atlas-based hippocampal-formation candidate visualization, bilateral external-auditory-meatus or ear-bar candidate localization, CT-derived inferior orbital-rim (orbitale) candidates, interaural/EBZ midpoint and stereotactic-frame candidate construction, multi-start consensus QA, independent landmark TRE, 3D Slicer scene packaging, provenance, and hashes. Use when asked to register monkey, macaque, or other NHP CT and MRI; investigate flips, double transforms, or misregistration; map an NHP hippocampal atlas; find ear holes, ear-bar zero, AP/ML zero, orbitale points, or Frankfurt/Horsley-Clarke axes; color bilateral brain-region candidates; build a preoperative research review scene; or validate such a package. Do not use to approve a surgery, craniotomy, trajectory, target, or safety margin.
---

# NHP CT-MRI, Hippocampal, and Cranial-Landmark QA

## Non-negotiable scope

Treat every derived image, label, point, midpoint, line, plane, and axis as a research candidate. Never approve surgery, recommend a craniotomy, select a trajectory or target, declare a safety margin, or silently promote a result to `FINAL` or `SURGICAL`. Preserve source files byte-for-byte. Stop at unresolved subject, acquisition, orientation, biological laterality, transform direction, atlas applicability, landmark definition, mechanical ear-bar contact, frame calibration, or expert-boundary uncertainty.

Use the state machine:

`UNVERIFIED_CANDIDATE -> RESEARCH_QA_PASS -> EXPERT_REVIEWED`

Use `QA_FAILED` for a failed gate. Automation may reach `RESEARCH_QA_PASS` only when a pre-approved protocol defines all required gates and thresholds. Only named professionals may assign `EXPERT_REVIEWED`. A technically reviewed image package still does not authorize surgical use.

## Start from a project configuration

1. Copy `assets/project-config.example.json` into a new derivative result directory.
2. Fill subject, species, exact input paths, acquisition identifiers, transform direction, software version, output directory, laterality evidence, atlas metadata, cranial-landmark methods, and protocol references.
3. Run `scripts/validate_project_config.py CONFIG.json`.
4. Freeze selected source inputs with `scripts/hash_manifest.py freeze`; verify the manifest before every later stage.
5. Never reuse a case-specific path, transform, initialization, side mapping, atlas transform, CT ray direction, landmark search box, intensity threshold, or TRE threshold for another animal.

## Execute the gated workflow

### Gate 0 - identity and source integrity

- Confirm one subject, intended scan dates, intended CT series, intended T1 series, and research purpose.
- For Analyze `.img`, run `scripts/check_analyze_pair.py`; require the paired `.hdr`. Treat ambiguous Analyze orientation as a hard gate requiring external confirmation.
- Prefer DICOM database import for CT. Record series UID, instance count, spacing, coverage, and orientation metadata.
- Hash inputs before conversion. Write all conversions and outputs under a new derivative directory.

Read `references/workflow.md` for the full phase checklist. Read `references/orientation-and-laterality.md` whenever direction, affine, RAS/LPS, qform/sform, screenshots, or biological sides are in scope.

### Gate 1 - orientation and biological laterality

- Inspect header geometry and three planes before registration.
- Distinguish voxel indices, file/world coordinates, Slicer world RAS, screen convention, and the animal's biological side.
- Confirm biological left/right using acquisition records, physical side markers, or independently documented asymmetric anatomy. Do not infer it from screen position or a candidate registration.
- Stop on qform/sform conflict, missing orientation metadata, suspected reflection, or contradictory side evidence. Never auto-flip.

### Gate 2 - registration candidate

- Default to T1 MRI fixed and CT moving; record `CT native -> MRI native` before running anything.
- Start with a proper rigid transform. Allow affine only when a documented acquisition or scale issue justifies it and rigid residuals show a systematic pattern. Do not default to nonlinear registration.
- Use multiple anatomically plausible initializations. Select by a predeclared transform-consensus rule, not by hippocampus or cranial-landmark position.
- Keep the fixed MRI untransformed. Compose transforms and resample the original CT once into MRI space using continuous interpolation.
- Treat optimizer success and multi-start agreement as repeatability evidence, not anatomical accuracy.

Read `references/registration-and-tre.md` before choosing initialization, similarity metrics, consensus rules, resampling, or TRE design. Read `references/slicer-operations.md` before operating 3D Slicer.

### Gate 3 - visual registration QA

- Review linked axial, coronal, and sagittal views over the full shared field of view.
- Use opacity flicker, checkerboard or edges, and stable landmarks at skull base, inner table, orbit, petrous bone, ear region, brain surface, ventricles, and temporal lobe.
- Save before/after and candidate-comparison images. Mark rejected candidates visibly and exclude them from the review scene.
- Reject continuous multi-slice mismatch, reflection, double transformation, or a transform that places brain targets outside the cranial cavity.

### Gate 4 - hippocampal-formation candidate

- Use only an atlas or model whose species, template version, age/development, in-vivo/ex-vivo status, resolution, contrast, hemisphere convention, and label definitions are documented for the case.
- Never silently substitute a human hippocampal model or a different NHP species.
- Propagate labels with nearest-neighbor interpolation and preserve subregion identity.
- Call atlas results `CANDIDATE`. If biological laterality is unconfirmed, use coordinate-side names rather than anatomical left/right.
- Require expert slice-by-slice review and manual or semiautomatic correction for uncertain borders.

Read `references/atlas-and-segmentation.md` before selecting or propagating an atlas.

### Gate 5 - cranial landmarks and candidate stereotactic frame

- Treat bilateral external-auditory-meatus/ear-bar points and bilateral inferior orbital-rim points as separate candidate sets with separate provenance.
- Prefer thin-slice native CT for bony anatomy and actual frame or ear-bar evidence for the mechanical contact. Use NMT full-head registration only to generate MRI search seeds when individual CT landmarks are not yet available.
- Package expert-marked native-CT bony EAM or calibrated mechanical-contact candidates with `scripts/prepare_manual_ct_ear_candidates.py`; require native CT IJK, the hashed CT and output reference, the locked transform binding, and the review record.
- Derive CT orbitale candidates in native CT geometry with an explicitly reviewed anterior ray direction, subject-specific bilateral search regions, and threshold-sensitivity runs. Never reuse another subject's indices or thresholds.
- Bind the orbitale report to hashed adjacent-slice and 3D bone QA with `assets/orbitale-review-evidence.example.json`. Keep expert status explicit; block CT-bony or mechanical frame construction while orbitale expert review is pending.
- Map native CT points to MRI world exactly once with the locked `CT native RAS -> MRI native RAS` transform. Do not both numerically transform the coordinates and attach the same parent transform.
- Keep biological laterality unassigned as `coordinate_side_A/B` until external evidence confirms it.
- Define the interaural/EBZ midpoint as the mean of the two accepted ear candidates. It is a theoretical origin candidate, not an individualized mechanical or surgical zero.
- Construct ML from the verified interaural line. Construct the ear-midpoint-to-orbitale-midpoint direction only after all four points share one world space. Orthogonalize axes, record sign evidence, and label the result a candidate frame until the actual apparatus is calibrated.
- Default the frame input policy to `REQUIRE_CT_BONY_EAM`. Permit template ear search seeds only under `ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY`; that policy must emit neutral axis names and cannot carry an apparatus-calibration claim.
- Require native CT/MRI adjacent-slice review, CT bone rendering, 3D intracranial plausibility, bilateral symmetry review without forcing symmetry, and named expert adjudication.

Read `references/cranial-landmarks-and-stereotactic-frame.md` before locating ear holes, orbitale, AP/ML zero, Frankfurt/Horsley-Clarke axes, or adding landmark markups. Use its scripts only after completing their case-specific configuration.

### Gate 6 - independent TRE

- Keep TRE landmarks independent of initialization, fitting, parameter tuning, candidate selection, visual adjustment, and cranial-landmark algorithms under evaluation.
- Use only definitions that a named expert approved for both modalities. Do not use the hippocampal label itself when it is not independently visible in CT.
- Require biological side confirmation before pairing lateralized landmarks.
- Generate blank Slicer markups with `scripts/slicer_create_tre_templates.py` and calculate TRE with `scripts/slicer_compute_tre.py`.
- Freeze and verify the native CT, native MRI, chosen transform, landmark specification, and blank templates before marking.
- Report every point, RMS, median, 95th percentile, maximum, signed R/A/S mean error, and spatial coverage. Apply no pass/fail grade unless an approved thresholds file is supplied.

### Gate 7 - package and scene validation

- Save the transform, CT resampled once into MRI space, hippocampal segmentation, labelmaps/models, requested cranial-landmark reports and markups, `.mrml`, QA images, provenance, config, frozen hashes, validation report, and limitations README.
- Keep fixed MRI, registered CT, segmentation, and world-coordinate landmark nodes free of parent transforms in the saved review scene.
- Remove hidden experimental masks, native/unregistered moving volumes, CLI history nodes, and rejected candidates from the review scene.
- Run `scripts/audit_mrml_package.py` and reload the scene in Slicer. Recompute package hashes after the last change.
- Follow `references/package-contract.md`; never name the package `complete`, `approved`, or `final` while TRE, landmark, frame, or expert review is pending.

## Stop conditions

Stop and report the exact blocker when any of these occurs:

- missing or unreadable companion/header files;
- ambiguous subject, series, units, coverage, orientation, or coordinate convention;
- qform/sform or DICOM orientation conflict;
- unresolved biological laterality or suspected reflection;
- unstable multi-start registration or persistent multi-slice mismatch;
- transform direction uncertainty or possible double application;
- atlas species/version/label incompatibility;
- unverified CT anterior ray direction, case-specific landmark ROI, or mechanical ear-bar contact definition;
- ear or orbit candidates outside bone/anatomy, unstable across thresholds/slices, or dependent on one extreme voxel;
- insufficient evidence to sign AP, ML, or DV axes or calibrate the frame;
- insufficient independent landmarks or validation leakage;
- missing approved thresholds when a pass/fail judgment is requested;
- failed hash, scene self-containment, or source-integrity check;
- unresolved hippocampal or cranial-landmark boundary or expert disagreement.

Do not guess around a gate. Produce diagnostic artifacts with `QA_FAILED` or `UNVERIFIED_CANDIDATE` status and request the missing evidence.

## Resource routing

- Use `references/workflow.md` for the end-to-end checklist and state transitions.
- Use `references/orientation-and-laterality.md` for coordinate and side decisions.
- Use `references/registration-and-tre.md` for registration design and independent validation.
- Use `references/atlas-and-segmentation.md` for NHP atlas applicability and hippocampal review.
- Use `references/cranial-landmarks-and-stereotactic-frame.md` for ear, orbitale, midpoint, axis, and frame-candidate work.
- Use `references/slicer-operations.md` for Slicer execution, interpolation, markups, screenshots, rendering, and scene handling.
- Use `references/package-contract.md` for deliverables, provenance, naming, and validation.
- Copy and complete files in `assets/`; never use example values as approved protocol content.
