# FAILS AT PACK: step1 runs ./does_not_exist.cwl.
#
# Expected: cwltool cannot resolve the reference, exit 1, nothing
# registered.
#
# This is the realistic multi-file failure: a workflow that is itself
# valid but whose sibling tool file was renamed, moved, or left
# uncommitted. Packing is what resolves `run:` references, so a workflow
# that packs is known to be self-contained -- which is exactly why the
# registered definition is the packed file and not this one.
cwlVersion: v1.2
class: Workflow

inputs:
  in_file: File

outputs:
  out_file:
    type: File
    outputSource: step1/result

steps:
  step1:
    run: ./does_not_exist.cwl
    in:
      infile: in_file
    out: [result]
