# FAILS AT PACK: `sample` is declared twice with different types.
#
# Expected: cwltool rejects it, exit 1, nothing registered.
#
# The inputs/outputs parser does not deduplicate ids -- it records the
# list as given, so a document with two `sample` entries would store two
# rows that no caller could disambiguate. This case documents that
# cwltool is what prevents that from reaching the API via the script.
# (A hand-written pack uploaded straight to NGS360 bypasses cwltool, so
# the remote path has no such guarantee -- see the README.)
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [echo]

inputs:
  sample:
    type: string
  sample:
    type: File

outputs: []
