# REMOTE PATH ONLY. Upload this file to NGS360 as-is -- do NOT pack it --
# then register it by file id:
#
#   upload_file(path=".../fail_remote_unpacked.cwl", ...)
#   register_workflow_from_file_id(file_id=<id>, name="t_unpacked")
#
# There is nothing wrong with this CWL. It is a perfectly valid, runnable
# tool. The failure is in what was uploaded: the schema reader parses the
# stored definition as JSON, and this is YAML.
#
# Expected:
#   the workflow IS registered, and the version IS deployed
#   io_warning: "...definition is not JSON... Expected the output of
#                'cwltool --pack <file>.cwl'..."
#   inputs_recorded: None    outputs_recorded: None
#   DB: inputs and outputs are both NULL
#
# This is the most likely real-world miss, because the file is valid CWL
# and the registration succeeds -- only the schema is silently absent.
# The warning naming `cwltool --pack` is the only signal the user gets,
# which is why it spells out the fix rather than just reporting a parse
# error.
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [wc, -l]

inputs:
  input_file:
    type: File
    inputBinding:
      position: 1
    doc: File to count lines in

outputs:
  line_count:
    type: stdout
