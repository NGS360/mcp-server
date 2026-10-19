# FAILS AT PACK: `Frobnicate` is not a CWL type.
#
# Expected: cwltool rejects it, exit 1, nothing registered.
#
# Worth having because the inputs/outputs parser deliberately does NOT
# validate type names -- it records whatever the document says, so that a
# CWL version introducing a new type still registers. cwltool is the
# component that enforces the type vocabulary, and this case proves the
# script relies on it rather than silently recording a nonsense type.
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [echo]

inputs:
  thing:
    type: Frobnicate

outputs: []
