# FAILS AT PACK: `label` is indented one space short, so it reads as a
# sibling of `message` rather than a key inside it.
#
# Expected: cwltool rejects it, the script dies before anything is
# created, exit 1. Nothing is uploaded and no workflow is registered.
#
# This is the single most common way a hand-edited CWL breaks, and the
# point of the case is that the failure lands at pack time -- long before
# the inputs/outputs parser is reached.
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [echo]

inputs:
  message:
    type: string
   label: wrong indentation

outputs: []
