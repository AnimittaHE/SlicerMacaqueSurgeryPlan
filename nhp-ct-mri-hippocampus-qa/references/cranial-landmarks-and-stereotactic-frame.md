# Cranial landmarks and candidate stereotactic frame

## Contents

1. Definitions and evidence hierarchy
2. Ear and ear-bar candidates
3. CT-derived orbitale candidates
4. Transform bookkeeping
5. Candidate origin and axes
6. QA, outputs, and stop rules
7. Background sources

## 1. Definitions and evidence hierarchy

Keep these concepts separate:

- **External auditory meatus (EAM):** an anatomical canal/opening.
- **Bony EAM landmark:** an expert-defined point on the osseous canal or aperture.
- **Ear-bar contact:** the point determined by bar geometry, insertion depth, tissue, and frame placement.
- **Interaural/EBZ midpoint:** the mean of two accepted bilateral ear-bar or protocol-defined EAM points.
- **Orbitale:** the protocol-defined lowest point on each inferior bony orbital rim, not the globe or lens edge.
- **Frankfurt/Horsley-Clarke candidate plane:** a plane constructed from accepted ear and orbitale landmarks under a named convention.

Use the evidence hierarchy:

1. Actual stereotactic apparatus or MRI/CT-visible frame markers with calibration.
2. Thin-slice native CT reviewed on bone windows and 3D rendering.
3. Subject MRI reviewed against registered CT.
4. Full-head macaque template propagation as a search seed only.

Do not let a template seed override visible subject anatomy. Do not call an air-lumen center a mechanical ear-bar contact without protocol and apparatus evidence.

## 2. Ear and ear-bar candidates

### CT-first path

Prefer native thin-slice CT for the bony canal. Place or refine bilateral candidates independently in native CT, then review at least three adjacent slices per plane and a 3D bone rendering. Distinguish EAM from mandibular condyle, mastoid/middle-ear cavities, air outside the head, cartilage, and partial-volume artifacts.

If an automated CT canal detector is used, require an approved landmark definition, subject-specific search region, sensitivity analysis, and expert correction. The current bundled workflow does not claim to infer the mechanical bar contact from CT alone.

After a named reviewer has placed the two candidates in the **native CT grid**, copy `assets/manual-ct-ear-candidates.example.json`, record the exact native CT continuous IJK values (integer voxel centers are also accepted), bind the hashed scene's named moving CT, fixed MRI, and locked CT-to-MRI transform with one case-specific `binding_id`, then run:

```powershell
python scripts/prepare_manual_ct_ear_candidates.py `
  --config manual_ct_ear_candidates.json `
  --output-json ct_ear_candidates.json `
  --output-markups ct_ear_candidates_UNVERIFIED.mrk.json
```

Use `landmark_class=BONY_EAM_ANATOMICAL_CANDIDATE` for a protocol-defined osseous landmark. Use `MECHANICAL_EAR_BAR_CONTACT_CANDIDATE` only when `assets/apparatus-contact-evidence.example.json` has been completed, hashed, and reviewed for the exact subject and apparatus. The apparatus record must reference the actual calibration artifact by path and SHA-256 and must bind the exact native-CT contact IJK values. The script maps native CT points into the common MRI world once and writes standalone markups with no parent transform; it validates provenance and geometry but does not validate the anatomical choice or independently recompute the apparatus calibration.

### Template/MRI search-seed path

Use `scripts/derive_template_earbar_candidates.py` only when an explicitly EBZ-defined full-head macaque template and a documented template-to-subject affine are available. The NMT v2 defaults `(-18, 0, 0)` and `(18, 0, 0)` RAS mm are bilateral search seeds on its EBZ ear-bar axis; they are not universal individual contact points.

Declare whether the stored ITK affine is a moving-to-fixed or fixed-to-moving **point map**. Confirm the declaration by comparing propagated points with the saved resampled template. A filename does not establish direction.

Example:

```powershell
python scripts/derive_template_earbar_candidates.py `
  --mri subject_T1.nrrd `
  --subject-id SUBJECT_ID `
  --output-space-name MRI_NATIVE_WORLD_RAS_MM `
  --template NMT_v2_full_head.nii.gz `
  --template-version NMT_v2.0_sym `
  --transform NMT_to_subject_affine.h5 `
  --transform-direction moving-to-fixed `
  --direction-evidence-json template_point_transform_evidence.json `
  --output-json earbar_search_candidates.json `
  --output-markups earbar_search_candidates_UNVERIFIED.mrk.json `
  --slicer-script add_earbar_search_candidates.py
```

Render native-MRI QA:

```powershell
python scripts/render_earbar_adjacent_slice_qa.py `
  --mri subject_T1.nrrd `
  --report earbar_search_candidates.json `
  --output earbar_adjacent_slice_QA.png
```

Reject a seed that sits outside the skull, follows generic background or air, lands on the mandible or a vessel, appears plausible on only one slice, or changes materially under reasonable full-head registration choices. Report rigid-versus-affine displacement as model sensitivity, not total error.

## 3. CT-derived orbitale candidates

Use `scripts/derive_ct_orbitale_candidates.py` for a deterministic, reviewable seed after creating a case-specific copy of `assets/ct-orbitale-config.example.json`.

The method:

1. Threshold bone in the native CT grid.
2. Cast rays along a case-confirmed anterior-to-posterior voxel direction.
3. Create a front-most-bone depth map.
4. Select a recessed orbital-aperture component inside each broad subject-specific search region.
5. Trace its inferior boundary using a declared inferior voxel-axis direction.
6. Use a robust boundary quantile instead of one extreme pixel.
7. Repeat over multiple depth thresholds and take a physical-space median candidate.
8. Verify that the candidate lands on thresholded bone.
9. Map the native CT RAS point into the requested output space with one explicit 4x4 matrix.

Example:

```powershell
python scripts/derive_ct_orbitale_candidates.py `
  --ct native_CT.nrrd `
  --config ct_orbitale_config.json `
  --output-json ct_orbitale_candidates.json `
  --output-markups ct_orbitale_candidates_UNVERIFIED.mrk.json
```

The ray axis, ray direction, inferior axis/direction, bone threshold, depth thresholds, bilateral search regions, component seeds, minimum component size, and rim offset are case-specific. Establish them from CT metadata and anatomy before running. Never copy a prior subject's voxel indices or thresholds into a new configuration.

Threshold agreement demonstrates local repeatability of the rule, not anatomical accuracy. Inspect the two candidates on native CT axial, coronal, sagittal, and 3D bone views. Confirm that each point is the intended inferior bony orbital rim, not globe, lens, soft tissue, zygoma, nasal bone, or an aperture spur.

After generating the orbitale report, copy `assets/orbitale-review-evidence.example.json`. Bind the exact orbitale report and at least one hashed native-CT adjacent-slice artifact plus one hashed 3D bone artifact. A template-seed visualization frame may retain `expert_anatomical_review_status=PENDING` but must expose that state. A CT-bony or mechanical-contact frame is blocked until the record says `REVIEWED_WITHIN_RECORDED_SCOPE` and has no unresolved conflict.

## 4. Transform bookkeeping

Keep algorithms in their native source geometry until candidate extraction is complete.

For CT-derived points:

```text
p_MRI_RAS = T_CT_native_RAS_to_MRI_native_RAS @ [p_CT_RAS, 1]
```

For markups already written in MRI world RAS:

- set no parent transform;
- do not harden the CT-to-MRI transform onto them;
- record the exact 4x4 matrix and its hash/provenance;
- keep the fixed MRI untransformed.

For markups kept in native CT RAS:

- either attach the CT-to-MRI parent transform in Slicer, or numerically map the points;
- never do both;
- record whether the node is native, parent-transformed, hardened, or numerically transformed.

3D Slicer displays world RAS. ITK and many NRRD files use LPS. Convert point coordinates with:

```text
RAS = (-LPS_x, -LPS_y, LPS_z)
LPS = (-RAS_x, -RAS_y, RAS_z)
```

Do not transform voxel indices directly with a world transform. Convert IJK to native physical coordinates first.

## 5. Candidate origin and axes

Only combine points after all four candidates are in the same physical world space and their transform provenance is frozen.

Let ear candidates be `E_A`, `E_B` and orbitale candidates be `O_A`, `O_B`:

```text
origin = (E_A + E_B) / 2
orbitale_mid = (O_A + O_B) / 2
e_ML_raw = normalize(E_B - E_A)
v_forward = orbitale_mid - origin
e_AP_raw = normalize(v_forward - dot(v_forward, e_ML_raw) * e_ML_raw)
e_DV_raw = normalize(cross(e_ML_raw, e_AP_raw))
```

This creates an orthonormal candidate basis. It does not by itself prove biological left/right, anterior sign, superior sign, or agreement with the actual frame. Verify signs using trusted anatomical landmarks or frame calibration before naming axes `ML`, `AP`, and `DV`; otherwise use neutral names such as `side_A_to_B`, `ear_mid_to_orbitale_mid`, and `plane_normal`.

Use `scripts/build_candidate_stereotactic_frame.py` to calculate the midpoint, orthonormal directions, side-pair asymmetry diagnostics, standalone Slicer markups, and an optional Slicer script from four common-space RAS points. The script opens and hashes the source ear/orbitale reports and refuses coordinates that do not exactly match them. It refuses anatomical axis labels unless its input explicitly documents sign confirmation.

Set `ear_input_policy` deliberately:

- `REQUIRE_CT_BONY_EAM` is the default research frame-candidate path.
- `REQUIRE_MECHANICAL_EAR_BAR_CONTACT` additionally requires the same hashed apparatus record carried by the mechanical-ear report.
- `ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY` never promotes template seeds to bony or mechanical contacts, forces neutral axis labels, and forbids an apparatus-calibration claim.

```powershell
python scripts/build_candidate_stereotactic_frame.py `
  --input candidate_frame_input.json `
  --output-json candidate_frame_metrics.json `
  --output-markups-dir candidate_frame_markups `
  --slicer-script add_candidate_frame.py
```

If axis signs are confirmed, copy the object structure from `assets/axis-sign-evidence.example.json` into `axis_sign_evidence`. The referenced laterality record must be subject-matched, hashed, confirmed, and conflict-free. The script rejects a signed basis that is reflected rather than right-handed.

For a point `P` after axis signs are confirmed:

```text
ML = dot(P - origin, e_ML)
AP = dot(P - origin, e_AP)
DV = dot(P - origin, e_DV)
```

Do not subtract raw Slicer RAS components unless the image was rigidly reoriented into the confirmed frame basis.

## 6. QA, outputs, and stop rules

Require:

- source hashes and exact image/transform identities;
- coordinate convention and units;
- coordinate-side names until laterality is confirmed;
- native IJK, native LPS/RAS, and common-world RAS for every candidate;
- algorithm configuration and threshold/registration sensitivity;
- adjacent-slice and 3D bone QA;
- markups labeled `UNVERIFIED` with no unintended parent transform;
- inter-ear distance, ear midpoint, orbitale midpoint, axis vectors, and orthogonality checks;
- named expert review and explicit unresolved questions;
- apparatus and frame-calibration status.

Stop when transform direction is not demonstrated, the CT ray direction or inferior axis is guessed, a search region is copied from another subject, a candidate is not on the intended bony landmark, template and subject anatomy disagree, laterality evidence conflicts, the four points do not share one space, axis signs are uncertain, or the mechanical contact/frame definition is missing for the intended use.

Never use these candidates alone to choose a craniotomy, target, trajectory, safety margin, or operative coordinate.

## 7. Background sources

- Jung B, et al. *A comprehensive macaque fMRI pipeline and hierarchical atlas.* NMT v2 uses a Horsley-Clarke stereotaxic orientation with an EBZ-defined origin: https://pmc.ncbi.nlm.nih.gov/articles/PMC9272767/
- Frey S, et al. *A frameless stereotaxic MRI technique for macaque neuroscience studies.* Describes a Frankfurt-plane workflow based on bilateral bony EAM and inferior orbital-rim landmarks: https://pmc.ncbi.nlm.nih.gov/articles/PMC3257065/

Use these definitions as background, not as validation of an individual animal's landmarks or apparatus.
