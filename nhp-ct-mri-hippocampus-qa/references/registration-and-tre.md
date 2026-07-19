# Registration design and independent TRE

## Rigid-first design

Use a proper rigid transform for cross-modal head alignment. Initialize from trustworthy geometry or documented pose evidence. Use affine only for a documented scale/shear problem after rigid QA. Treat nonlinear registration as a separate research method requiring deformation-field and folding checks; never make it the default for skull-to-brain preoperative review.

## Multi-start consensus

Predeclare starts and selection rules. For each result, save initialization and optimizer parameters, the final 4×4 matrix and direction, determinant and orthogonality error, transformed shared physical test points, pairwise maximum displacement and relative rotation, logs, runtime, and software version.

Select the largest stable transform-consensus cluster and a medoid or other predeclared representative. Never select using hippocampal position, final TRE points, or the answer desired by a reviewer. Consensus demonstrates repeatability, not accuracy.

## Resampling

- Keep the fixed MRI unchanged.
- Compose transformations and resample the original CT once.
- Use a continuous interpolator for CT/MRI intensity images.
- Use nearest-neighbor for labels and masks.
- Never overwrite original headers or source images.

## Independent TRE design

Lock the transform and algorithm before collecting test landmarks. Landmarks used for initialization, fitting, parameter tuning, or selecting a candidate are not independent test points.

Require expert-approved definitions visible in both modalities, independent marking in native CT and native MRI, biological-side confirmation for paired lateral points, broad three-dimensional coverage, and target-adjacent coverage only when genuinely visible in both modalities. Exclude teeth, mandible, external ear, deformable soft tissue, and any structure requiring guessing. Do not use an atlas hippocampus as a CT landmark.

Report per-point error, RMS, median, 95th percentile, maximum, signed mean R/A/S vector, point-set extent, and reviewer/repeatability metadata. Separate target-adjacent statistics if the protocol defines such landmarks.

## Threshold policy

Do not invent universal acceptance thresholds. Load thresholds only from a file that names the approved protocol, approver, role, date, metrics, and limits. Without it, calculate descriptive TRE and report `NO_APPROVED_ACCEPTANCE_THRESHOLDS`.

Optimizer cost, mutual information, NCC, Dice, overlay appearance, and multi-start consensus cannot replace independent TRE. TRE also does not equal hippocampal target error or the full stereotactic error budget.
