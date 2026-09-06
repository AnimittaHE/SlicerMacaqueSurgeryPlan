# Smooth skull-curvature models: Slicer → Blender → STEP

This is the maintained model-generation branch. Keep CT/MRI registration and landmark workflows unchanged. Work from an independently saved scene copy and preserve source hashes. Outputs remain research geometry candidates.

## Inputs and geometry choices

Record the selected scene/skull segment, saved smoothing settings, rectangle dimensions or opposite corners, directed axis, in-plane reference and top-plane rule. Reuse prior confirmed user choices. Do not hardcode an animal's coordinates, 8×8 mm size, smoothing factor or 1 mm thickness into the workflow.

For origin c and outward unit vector s, project the in-plane reference onto the perpendicular plane to obtain unit u; use v=s×u. Points are c+x*u+y*v+h*s. A diagonal alone does not determine the rectangle. Reject degenerate inputs. If saved AP/ML and the requested normal disagree, report their angle and follow the user's established priority; do not claim both constraints are exact.

The inner skull wall represents broad cranial curvature, not MRI-segmented cortex. Artificial-dura thickness, compression and pressure are separate from geometric smoothing or block thickness.

## Export the existing smooth surface

Use the scene's selected Skull closed surface with its saved conversion settings. `CreateClosedSurfaceRepresentation()` recreates it from labels with those settings; `GetClosedSurfaceRepresentation(segmentID, polyData)` retrieves it. Do not rebuild a rough threshold surface when the chosen smooth mesh exists. Smooth shading changes appearance, not geometry.

Inspect labelmap direction/origin and parent transforms together. No parent can mean registration is already embedded in the geometry. Apply a parent to a mesh copy only when needed to reach world space. Never reapply CT→MRI to registered vertices; a geometry-only task does not require new registration.

Export skull and crossing prism with identical conventions. Direct VTK STL export in RAS mm with `_RAS_mm.stl` names is one reliable choice. STL has no unit or coordinate metadata; do not mix it with Slicer-written LPS STL. Verify imported bounds and several asymmetric corresponding vertices; bounds alone cannot exclude reflection. In Blender retain relative placement and numerical coordinates. Metric unit scale 0.001 can label raw millimetres without scaling geometry again.

## Run the Blender Boolean

Create a closed rectangular prism spanning the local skull, from a cavity-side plane through the outer wall. Side walls follow s and top is perpendicular to s. Keep this construction prism tall until extraction is complete, even when the final top lies inside the original bone thickness.

Import both meshes and execute an Exact Boolean INTERSECT on a prism copy, with skull as operand. Save the `.blend` and Boolean bone patch. Do not describe ray casting alone as a Boolean operation. Inspect empty output, inverted normals, disconnected fragments and degenerate/duplicate triangle cleanup; do not silently fill anatomical holes to force success.

Cast rays through the full footprint from the cavity side toward s; select the first inner-wall hit. Check normals and source context to distinguish inner wall, outer wall, bone cavities and Boolean side caps. At boundaries use a documented tiny inset to avoid cap hits. Retain samples and require full coverage rather than filling missed rays. A 65×65 grid over 8 mm worked in the motivating case; it is not a universal setting.

## Fit broad curvature and set thickness

Initially fit h(x,y) as one global bicubic patch with 4×4 control points. Least-squares bicubic fitting without interior knots provides this behavior. If using RectBivariateSpline, verify four poles per dimension. Avoid tightening tolerances until hundreds of poles reproduce voxel ripples. If one patch cannot represent the broad shape, inspect residuals and document increased complexity.

Report signed, RMS and maximum errors against the chosen smooth mesh, including an independent interstitial grid. These are approximation errors, not anatomical or registration accuracy. Preserve comparisons when smoothing changes. An unconstrained fit can lie on either side of the surface; do not claim no penetration or safe tissue contact.

For user-requested minimum axial thickness t>0, set `H=max(h over the rectangle)+t`. The top is c+x*u+y*v+H*s. This preserves the bottom, makes the thinnest location t and allows thicker regions elsewhere. A thickness-only revision must reuse the bottom/poles and prove unchanged shape and placement. Axial thickness is distinct from the shortest distance between arbitrary surfaces.

Calculate continuous extrema on the edges and interior, not just STL/grid vertices. For one bicubic Bezier patch, use de Casteljau subdivision and the control-net convex-hull bound: corner samples give a lower bound and maximum control height an upper bound. Refine until the recorded bound gap is small, then choose H=upper_bound+t. Numerical precision is not fabrication precision.

## Build and verify an editable solid

Create one B-spline bottom, one planar top and four side faces bounded by the bottom curves and top edges. For this rectangular height field the four sides are planar. Sew a closed shell and orient a single BREP solid with an available CAD kernel, such as OpenCascade. Export STEP in millimetres with world placement retained.

For tensor B-spline heights, Greville abscissae reproduce linear x/y pole coordinates; the fitted coefficients supply the s component. Check CAD surface evaluations against fitted world points. Verify positive volume, valid single solid, expected face count, top planarity, footprint, minimum thickness and STEP reload volume/geometry. Keep display triangulation separate from the continuous surface. STEP permits subsequent SolidWorks solid operations but carries no native feature history. Claim SolidWorks import testing only if performed.

## Scene and deliverables

Return STEP, preview STL, `.blend` with skull/prism/Boolean patch, source samples, compact surface parameters, coordinate/fit/thickness reports, README and self-contained `.mrml` package. Thickness-only edits may reuse previous Boolean provenance rather than rerun extraction.

Add the generated model in world RAS without a parent. Save with explicit storage conventions and reload. Verify internal file references, coordinate round trips, zero open/nonmanifold edges and source hashes. Preserve the original scene's registration hierarchy in the copied context; do not remove a needed native CT parent to satisfy a generic model audit. Apply parent-free checks to the derived world model and fixed reference, and describe audit scope honestly.

After moving packages, recheck references. Keep one obvious current scene entry point and clearly mark historical construction geometry. Delete older results only when requested. Keep subject images, coordinates, private paths and binaries out of the public skill repository.

## Legacy MRI-mask experiments

`slicer_generate_brain_contact_block.py` and `brain-contact-config.example.json` remain for explicitly requested MRI-mask experiments. They do not implement this Blender/STEP workflow and are not an automatic fallback. A true cortex-derived task needs an appropriate subject-specific brain surface; switching anatomical source must be explicit.
