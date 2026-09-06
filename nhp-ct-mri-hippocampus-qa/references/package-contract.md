# Candidate package contract

## Required contents

```text
candidate-package/
  project-config.json
  CANDIDATE_STATUS.txt
  scene_CANDIDATE_EXPERT_REVIEW_REQUIRED.mrml
  MRI_reference_untransformed.*
  CT_registered_once_in_MRI_space_CANDIDATE.*
  CT_to_MRI_rigid_CANDIDATE.*
  hippocampal_formation_CANDIDATE.seg.nrrd
  coordinate_side_A_labelmap.*
  coordinate_side_B_labelmap.*
  models_CANDIDATE_ONLY/
  cranial_landmarks_CANDIDATE_ONLY/
    ear_coordinate_side_A_B_UNVERIFIED.mrk.json
    earbar_search_candidates.json
    manual_ct_ear_config.json
    ct_ear_candidates.json
    orbitale_coordinate_side_A_B_UNVERIFIED.mrk.json
    ct_orbitale_candidates.json
    candidate_frame_markups/
      cranial_landmarks_and_midpoints_UNVERIFIED.mrk.json
      *_axis_candidate_UNVERIFIED.mrk.json
      ear_mid_to_orbitale_mid_UNVERIFIED.mrk.json
    candidate-frame-input.json
    orbitale-review-evidence.json
    candidate_frame_metrics.json
  brain_contact_CANDIDATE_ONLY/
    brain-contact-config.json
    input_rectangle_UNVERIFIED.mrk.json
    projection_direction_UNVERIFIED.mrk.json
    contact_surface_UNVERIFIED_CANDIDATE.stl
    closed_contact_block_UNVERIFIED_CANDIDATE.stl
    depth_maps_raw_outer_gaussian_final_mm.npy
    brain_contact_provenance_UNVERIFIED_CANDIDATE.json
  qa_images/
  tre_review/
  provenance/
    critical-node-inventory.json
    module-gate-records/
  VALIDATION_REPORT.json
  VALIDATION_REPORT.txt
  SHA256SUMS.json
  README.md
```

Include hippocampal, cranial-landmark, and brain-contact files only for requested modules. Adapt extensions to the environment but preserve roles, provenance, coordinate space, and candidate status.

For ear evidence, designate exactly one authoritative candidate pathway in the project config and README: template search seeds, expert-defined CT bony EAM, or calibrated mechanical ear-bar contacts. If template and CT files are both retained for comparison, label the non-selected set `NONAUTHORITATIVE_COMPARISON_ONLY`; never let both silently feed one frame. Bind the authoritative `candidate-frame-input.json` by path and SHA-256 in the project config, and require its `ear_input_policy` to match the selected pathway.

## README fields

Include the research warning, subject/acquisition identifiers, Slicer/modules, fixed/moving definitions and transform direction, registration parameters and selection rule, interpolation, laterality evidence, atlas/model provenance and applicability, hippocampal method and uncertain borders, cranial-landmark operational definitions and methods, native/common point spaces, EBZ midpoint status, candidate-frame construction and sign evidence, apparatus-calibration status, requested brain-contact footprint/direction/mask binding/smoothing/dura offset/mesh QA, QA findings, rejected candidates, TRE design/results or missing status, limitations, required reviews, and current state.

## QA images

Include pre-registration versus chosen candidate, all three planes, temporal-lobe-focused views, and 3D context. When cranial landmarks are requested, add blinded native-source adjacent-slice views and CT 3D bone views before any cross-method reconciliation figure. Put subject ID, space, coordinate convention, candidate state, and `NOT FOR SURGICAL USE` on durable figures. Mark rejected methods visibly.

## Technical validation

- Reload the scene.
- Copy `assets/critical-node-inventory.example.json` to `provenance/critical-node-inventory.json` after the scene is final. Bind it to the final scene's package-relative path and SHA-256. Inventory every coordinate-bearing Volume, LabelMap, Segmentation, Model, Markups, ROI, and Transform node by exact MRML `id`, `name`, and XML `tag`; give each a unique role and explicitly set `expected_parent_transform` to `null`.
- Check every storage reference exists and stays inside the package.
- Reject URIs and unexpected absolute/outside-package paths.
- Reject hidden old-experiment, CLI, native moving-volume, or rejected-candidate nodes.
- Run `scripts/audit_mrml_package.py --scene <scene> --package-root <package> --critical-node-inventory <package>/provenance/critical-node-inventory.json --report <package>/VALIDATION_REPORT.json`. The inventory is mandatory; command-line `--critical-node-name` values are additional checks and never replace it.
- Require the static audit to resolve both modern semicolon-delimited MRML `references` and legacy `*NodeRef` attributes, reject malformed or dangling references, prove that no coordinate-bearing node was omitted from the inventory, and check every inventoried node has no parent transform. A transformed critical node is a double-transform risk and fails validation even if it looks plausible in one view.
- Compare packaged versus scene dimensions, geometry, and arrays.
- Check transform determinant, orthogonality, direction, and expected hash.
- Verify segmentation names, colors, label codes, and geometry.
- Verify every landmark's source space, common world space, node parent transform, report hash, and coordinate-side label.
- For current skull-model outputs, follow `skull-blender-modeling.md`: freeze the smooth surface/config, verify world-space coordinates, full-footprint Boolean inner-wall coverage, off-grid fitting errors, continuous minimum axial thickness, valid STEP reload and zero boundary/non-manifold preview edges. Preserve required source-context transforms and audit the derived world-space model separately. The old mask no-penetration invariant applies only to explicitly requested legacy MRI-mask experiments.
- Recompute midpoints and frame vectors from packaged points; check unit length, mutual orthogonality, handedness, degeneracy, and sign-evidence status.
- Recompute package hashes after every final change and verify them independently.

Technical validation never upgrades the package beyond its research candidate state.
