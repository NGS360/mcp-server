# PACKS FINE, SCHEMA CANNOT BE RECORDED: `.nan` is a valid YAML float,
# and cwltool accepts it, so this packs without complaint. But cwltool
# writes it into the packed JSON as the bare literal `NaN`, which is not
# valid JSON -- the JSON spec has no NaN. Sending it to the API would
# have produced a malformed request body and failed the whole version
# create.
#
# Expected:
#   exit 0 -- the workflow IS registered, with a deployed Omics version
#   stderr:  reason: a parameter value is not valid JSON (...)
#            warning: could not read inputs/outputs from ...
#   DB:      inputs and outputs are both NULL
#
# NULL here means "we never managed to read the schema", which is
# deliberately distinct from `[]` ("this workflow declares no
# parameters" -- see pass_no_parameters.cwl). The registration itself
# must not be blocked by a schema we could not capture.
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [echo]

inputs:
  threshold:
    type: float
    default: .nan
    doc: Score cutoff; .nan is how a CWL author writes "unset".

outputs: []
