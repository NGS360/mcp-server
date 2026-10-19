cwlVersion: v1.2
class: CommandLineTool
baseCommand: [wc, -l]

inputs:
  files:
    type: File[]
    doc: Step-level input; must not appear in the workflow's schema
    inputBinding:
      position: 1
  min_quality:
    type: int
    default: 20

outputs:
  counts:
    type: stdout
