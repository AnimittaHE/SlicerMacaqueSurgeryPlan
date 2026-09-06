# MRI-derived brain-surface contact geometry

Legacy reference for explicitly requested MRI-mask experiments only. For specified curved-bottom models use [skull-blender-modeling.md](skull-blender-modeling.md), the maintained smooth-skull Blender Boolean and STEP workflow. Do not automatically route a CAD modeling request to the legacy generator below.

## Scope

Use this branch to create a rectangular, directed, MRI-brain-mask-derived contact-surface candidate and a closed test block for downstream CAD inspection. It does not choose a craniotomy, target, trajectory, implant pressure, clearance, fixation, or safety margin. The footprint and direction must come from the user or a documented expert-reviewed planning step.

Every output must remain `UNVERIFIED_CANDIDATE` and `accepted_for_surgical_use: false`.

## Required inputs

- A frozen, SHA-256-bound individual-subject binary brain mask in MRI native world space.
- Two opposite corners of the top rectangle in 3D Slicer world RAS millimetres.
- A directed line in the same RAS space; start is outside/top and end points toward the brain.
- An in-plane U reference vector.
- Explicit sampling, smoothing, dura-offset, and output parameters.

Two diagonal points plus a projection direction do not uniquely determine a rectangle's edge directions in arbitrary 3D space. `plane_u_reference_ras` resolves that remaining degree of freedom. For an S-to-I projection with a rectangle intended to follow Slicer R/A axes, `[1, 0, 0]` is a reasonable explicit reference; do not silently reuse it when another orientation is intended.

The brain-mask node must have no parent transform. If a mask is derived from a transformed node, resample it once into the frozen MRI reference geometry and preserve the derivation record before using this branch.

## Deterministic construction

1. Project the two diagonal points onto their common plane only within the configured tolerance; otherwise stop.
2. Construct orthonormal U/V axes perpendicular to the normalized directed line.
3. Sample the complete rectangle, including edges, at the configured spacing.
4. Require every top-grid sample to lie outside the brain mask.
5. Cast rays along the directed line and find the first outside-to-inside mask transition. Refine each transition by binary subdivision.
6. Require the configured hit coverage. Default to 100% and keep nearest-neighbour hole filling disabled; a missed ray normally indicates an invalid footprint, direction, coverage, or mask.
7. Convert first-hit distances into an outer envelope with a minimum-depth filter, then apply Gaussian smoothing.
8. Clamp the smoothed depth to the raw first-hit depth minus the configured non-negative dura offset. This prevents the derived surface from entering the binary brain mask along the projection direction.
9. Build both an open contact surface and a watertight closed block between the input top plane and the contact surface.
10. Save STL through Slicer so the on-disk LPS convention round-trips to the same Slicer RAS geometry.

Run `scripts/slicer_generate_brain_contact_block.py` with a completed copy of `assets/brain-contact-config.example.json`. Set `NHP_BRAIN_CONTACT_CONFIG` to the absolute config path. For headless execution, also set `NHP_BRAIN_CONTACT_EXIT_WHEN_DONE=1`.

## Artificial-dura parameters

`outer_envelope_window_mm` controls how broadly the surface bridges local depressions such as sulci. `gaussian_sigma_mm` controls residual smoothness. These are geometric filters, not a biomechanical model.

`dura_offset_mm` is an offset opposite the projection direction. Keep it at zero until the actual artificial-dura thickness, compression, wrinkling, material batch, fixation, and intended preload are documented. A positive value does not simulate nonlinear deformation or pressure.

When smoothing materially affects design, create at least a moderate and a stronger candidate with the same frozen inputs. Compare raw-versus-final depth maps and record the maximum bridge distance. Do not select a parameter set solely because the rendering looks smooth.

## Required QA

- Freeze and hash the brain mask and config.
- Confirm all inputs are in one MRI world RAS space and have no parent transform.
- Require the top-grid-inside count to be zero.
- Require the ray-hit coverage to meet the predeclared threshold; prefer 100%.
- Confirm `raw_first_hit_depth - final_depth >= dura_offset` everywhere.
- Require zero boundary edges and zero non-manifold edges for the closed block.
- Reload each STL in Slicer and require maximum RAS bounds discrepancy no greater than 0.01 mm.
- Review the brain-mask boundary slice by slice over the complete footprint.
- Display the raw mask surface, smoothed candidate, registered CT/skull context, and input direction together.
- Inspect edge transitions, possible mask leakage, deep-groove bridging, surface gaps, and unintended contact outside the intended footprint.
- Preserve the config, provenance JSON, markups, STL hashes, screenshots, and rejected smoothing variants.

## Stop conditions

Stop without a geometry candidate when any of these occurs:

- ambiguous RAS/LPS convention, units, transform direction, or parent transform;
- diagonal points outside the configured common-plane tolerance;
- reference vector parallel to the projection direction;
- any top-grid sample inside the mask;
- insufficient ray-hit coverage or a ray entering the wrong disconnected mask component;
- brain-mask boundary uncertainty under the footprint;
- smoothing or offset that violates the no-penetration invariant;
- open or non-manifold closed-block mesh;
- STL reload geometry mismatch;
- missing expert definition of footprint, direction, artificial-dura offset, or mechanical constraints when the result would be used beyond visualization.

## Deliverables

- completed brain-contact configuration and its SHA-256;
- input rectangle and directed-line markups;
- contact-surface-only STL;
- closed-block STL;
- provenance JSON with coordinates, basis, mask binding, grid, hit coverage, raw/final depth ranges, smoothing parameters, mesh QA, and output hashes;
- deterministic NumPy depth-map stack containing raw first-hit, outer-envelope, pre-clamp Gaussian, and final clamped depths;
- Slicer screenshots and a limitations note;
- optional moderate/strong smoothing comparison candidates, clearly distinguished and retained for review.

The closed block is intended as a geometric intermediary for Blender, SolidWorks, or equivalent CAD. Boolean operations, wall thickness, fastening, tolerances, manufacturability, sterilization, and load/pressure analysis remain separate reviewed engineering steps.
