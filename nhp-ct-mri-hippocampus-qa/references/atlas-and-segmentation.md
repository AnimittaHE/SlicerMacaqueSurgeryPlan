# NHP atlas applicability and hippocampal candidates

## Applicability record

Record subject and atlas species/subspecies, age/developmental stage, in-vivo or ex-vivo acquisition, template name/version/resolution/contrast, source citation, license, symmetry and hemisphere convention, exact hippocampal labels, registration method, pathology/intervention/artifact limitations, and justification for every mismatch.

Do not silently interchange rhesus, cynomolgus, marmoset, other NHP, or human resources.

## Candidate generation

- Register atlas anatomy to the individual's MRI without using CT or a desired surgical target to bias selection.
- Propagate labels with nearest-neighbor interpolation.
- Preserve original label codes and create provenance hashes.
- Keep hippocampus proper, subicular complex, fimbria, and other subregions separable even when presenting a union.
- Check connected components, side overlap, XOR against source label unions, geometry, and parent transforms.

## Review

Review the candidate slice by slice in native MRI space. Require an NHP neuroanatomy expert to verify head/body/tail continuity and borders with ventricle, amygdala, parahippocampal/subicular regions, white matter, and fimbria. Mark ambiguous borders explicitly and correct them manually or semiautomatically.

An atlas propagation, model output, smooth 3D surface, or location inside the skull is not individual ground truth. Do not calculate a trajectory or safety margin from an unreviewed candidate.

## Laterality and display

Use distinct colors and separate segments. Until biological side is externally confirmed, name them by coordinate side and state that anatomical left/right is unresolved. A display color or filename must never be the sole laterality record.
