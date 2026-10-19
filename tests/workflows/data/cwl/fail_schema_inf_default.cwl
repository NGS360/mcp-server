# PACKS FINE, SCHEMA CANNOT BE RECORDED: same root cause as
# fail_schema_nan_default.cwl, but with `.inf` instead of `.nan`.
#
# This one matters more in practice: `.inf` as "no upper limit" is a
# reasonable thing for a bioinformatician to write by hand, whereas
# `.nan` usually arrives by accident. cwltool emits it as the bare
# literal `Infinity`, which JSON does not define.
#
# Expected:
#   exit 0 -- the workflow IS registered
#   stderr:  reason: a parameter value is not valid JSON (...)
#   DB:      inputs and outputs are both NULL
#
# If you want this workflow's schema recorded, the fix is in the CWL:
# write a finite sentinel (e.g. 1e9) or drop the default and make the
# input optional.
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [echo]

inputs:
  max_coverage:
    type: float
    default: .inf
    doc: Upper coverage bound; .inf means no limit.

outputs: []
