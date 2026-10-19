# CONTROL CASE -- this one must SUCCEED, and is here to prove the
# failures above are recorded distinguishably.
#
# A workflow that legitimately declares no inputs and no outputs.
#
# Expected:
#   exit 0
#   stdout:  inputs:  0 (0 required, 0 optional)
#            outputs: 0
#   DB:      inputs = []   outputs = []     <-- empty lists, NOT NULL
#
# The whole point of the pair (this file vs. fail_schema_nan_default.cwl)
# is that the two states are different rows in the database:
#
#   []    the schema was read, and the workflow takes no parameters
#   NULL  the schema was never read -- go look at the definition
#
# If a failing case ever writes `[]`, that distinction is gone and a
# broken upload becomes indistinguishable from a parameterless workflow.
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [date]

inputs: []
outputs: []
