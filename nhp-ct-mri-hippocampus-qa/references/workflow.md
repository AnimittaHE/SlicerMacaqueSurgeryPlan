# End-to-end gated workflow

## Contents

1. Project states
2. Phase checklist
3. Rejection and recovery
4. Expert handoff

## 1. Project states

| State | Meaning | Who may assign it |
|---|---|---|
| `UNVERIFIED_CANDIDATE` | Derived images exist; one or more validation gates remain | Automation |
| `QA_FAILED` | A required gate failed; diagnostic outputs only | Automation or reviewer |
| `RESEARCH_QA_PASS` | All pre-approved technical gates passed; expert review still required | Automation under an approved protocol |
| `EXPERT_REVIEWED` | Named qualified reviewers accepted the defined research use | Authorized reviewers only |

Never use `FINAL`, `APPROVED`, `SURGICAL_TARGET`, or equivalent as an automatic status.

Before assigning `RESEARCH_QA_PASS` or `EXPERT_REVIEWED`, lock and hash-verify the chosen transform and create one reviewed gate record per enabled module from `assets/module-gate-evidence.example.json`. Bind every gate record to its exact source-output hashes. When independent TRE is enabled, also supply the approved protocol-specific thresholds file. `EXPERT_REVIEWED` additionally requires a named scope and authorization record; it still does not authorize surgery.

## 2. Phase checklist

### Phase A — intake

- Record subject ID, species, scan dates, protocol IDs, and intended research use.
- Enumerate every candidate CT/MRI series; never choose solely by filename.
- Verify Analyze pairs, DICOM series continuity, file readability, dimensions, spacing, units, and coverage.
- Freeze source hashes and create a derivative-only output root.

Exit only when subject and acquisitions are unambiguous.

### Phase B — orientation audit

- Record source coordinate convention and Slicer world convention.
- Compare DICOM tags, NIfTI affine/qform/sform, Analyze limitations, and three-plane anatomy.
- Record biological laterality status, evidence, confirmer, role, and date.
- Do not correct a suspected flip automatically.

Exit only when transformable geometry is understood. If laterality remains unconfirmed, block lateralized names and TRE pairing.

### Phase C — CT-to-MRI rigid candidate

- Declare fixed MRI, moving CT, and `CT native → MRI native` direction.
- Create plausible initial transforms without using final TRE points.
- Run at least the protocol-specified number of starts.
- Compare transforms using physical test-point displacement and relative rotation, not only optimizer scores.
- Select using a predeclared consensus rule. Preserve every run's parameters and logs.

Exit with one candidate or `QA_FAILED` if no stable consensus exists.

### Phase D — visual registration QA

- Examine full-volume axial/coronal/sagittal overlays and temporal-lobe-focused views.
- Check skull inner table, cranial base, orbit, petrous/ear structures, brain surface, ventricles, and temporal lobe.
- Save initialization, rejected-candidate, chosen-candidate, opacity-flicker, edge, and 3D context images.
- Record named reviewers and disagreements.

### Phase E — hippocampal candidate

- Complete the atlas applicability record before registration or inference.
- Map labels in MRI space; use nearest-neighbor interpolation for labels.
- Preserve individual subregions and create a union only as an additional output.
- Use coordinate-side names until biological laterality is externally confirmed.
- Save slice-by-slice review material and mark uncertain borders.

### Phase F — cranial-landmark and candidate-frame branch

- Run this branch only when ear/EAM, ear-bar zero, orbitale, Frankfurt/Horsley-Clarke, or AP/ML/DV candidates are requested.
- Record a protocol definition for each point before locating it; keep anatomical EAM, bony landmark, and mechanical ear-bar contact distinct.
- Prefer native thin-slice CT and apparatus evidence. Use full-head template propagation only as a search seed.
- Derive ear and orbitale candidate sets independently; do not tune either set to make the final axes look expected.
- Keep coordinate-side A/B names until biological laterality is confirmed.
- Map native CT points into MRI world exactly once with the locked transform and no parent transform on already mapped markups.
- Review adjacent native slices and 3D bone context; record threshold, registration-model, and reviewer sensitivity.
- Compute an ear midpoint and candidate frame only after all four points share one frozen physical space.
- Require independent sign evidence before calling axes ML, AP, or DV; otherwise retain neutral candidate-axis names.

Exit with `UNVERIFIED_CANDIDATE`, `QA_FAILED`, or named expert review. Never interpret technical completion as apparatus calibration or surgical authorization.

### Phase G — independent TRE

- Lock the chosen transform before landmark collection.
- Mark native CT and native MRI independently in separate scenes.
- Exclude any point used for fitting, tuning, or selecting the transform.
- Freeze source volumes, transform, landmark specification, and templates.
- Compute per-point and summary errors in millimetres; report distribution and spatial coverage.
- Apply only thresholds from a pre-approved, named protocol.

### Phase H — smooth skull modeling with Blender

- Run only when a user-defined or documented expert-defined contact footprint and projection direction are available.
- Freeze the selected scene's existing smooth skull surface and record the rectangle, directed line, in-plane reference, surface parameters and minimum-thickness rule in world RAS millimetres.
- Do not infer a craniotomy, target, trajectory, implant pressure, clearance, or safety margin from the hippocampal or frame candidates.
- Follow `references/skull-blender-modeling.md`: Blender Exact Boolean intersection, cavity-facing inner-wall extraction, compact bicubic fitting and a planar-top STEP solid.
- Validate full ray coverage, independent approximation errors, continuous minimum axial thickness, watertightness, coordinate round trips and STEP reload geometry.
- Preserve bottom geometry during thickness-only edits and record source-to-fit deviations. Do not claim no penetration for an unconstrained fit.

Exit with `UNVERIFIED_CANDIDATE` or `QA_FAILED`; automation must not promote a contact model to surgical or implant-ready status.

### Phase I — package validation

- Build a self-contained candidate package, including requested cranial-landmark reports, markups, and QA.
- Remove hidden experimental nodes, parent transforms, native moving volumes, and CLI history.
- Reload the `.mrml`; check every storage reference and critical array/geometry identity.
- Generate and independently verify the final package hash manifest.

## 3. Rejection and recovery

On a failed gate:

1. Preserve the failed candidate under a clearly rejected audit directory.
2. Write the reason and evidence; never overwrite it with a later candidate.
3. Return to the earliest affected phase.
4. Change one justified factor at a time when feasible.
5. Re-run every downstream gate after any transform, resampling, atlas, label, or scene change.

## 4. Expert handoff

Provide source identifiers, fixed/moving definitions, transform direction, atlas/version, cranial-landmark definitions and methods, coordinate convention, candidate origin/frame status, apparatus-calibration status, brain-contact footprint/direction/mask/smoothing provenance when requested, candidate state, uncertainty list, QA images, TRE protocol/results, hashes, and exact questions requiring adjudication. Never ask reviewers to infer which result was used.
