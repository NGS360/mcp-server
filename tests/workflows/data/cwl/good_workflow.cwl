# A multi-step Workflow. Packing puts it and its step tool in a $graph;
# only "#main"'s parameters are the workflow's own. The step tool also
# declares inputs (files, min_quality) as a decoy: none of them may be
# recorded. contamination_values is the awkward optional-array-of-union
# shape seen in the WES merge workflow.
cwlVersion: v1.2
class: Workflow
label: Example workflow for registration tests

inputs:
  reads:
    type: File[]
    doc: Input reads, one file per lane
  min_quality:
    type: int
    default: 20
    doc: Minimum base quality
  sample_id:
    type: string
    label: Sample ID
  reference:
    type: File?
    doc: Optional reference genome
  contamination_values:
    type:
      - "null"
      - type: array
        items: [float, string]
    doc: Per-caller contamination estimates

outputs:
  line_counts:
    type: File
    outputSource: count/counts
    doc: Line counts for all reads

steps:
  count:
    run: good_workflow.steps/count_lines.cwl
    in:
      files: reads
      min_quality: min_quality
    out: [counts]
