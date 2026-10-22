# A single CommandLineTool covering the common parameter shapes: a
# label-only doc, a plain doc, an optional input, an enum with a default.
# cwltool packs a lone tool as a bare process with id "#main".
cwlVersion: v1.2
class: CommandLineTool
label: Example tool for workflow-registration tests
baseCommand: [cp]

inputs:
  source_file:
    type: File
    label: Source file to copy
    inputBinding:
      position: 1
  target_filename:
    type: string
    doc: Name for the output file
    inputBinding:
      position: 2
  verbose:
    type: boolean?
    doc: Print each file as it is copied
  mode:
    type:
      type: enum
      symbols: [fast, safe]
    default: safe
    doc: Copy strategy

outputs:
  copied_file:
    type: File
    doc: The copy
    outputBinding:
      glob: $(inputs.target_filename)

requirements:
  InlineJavascriptRequirement: {}
