# CWL fixtures for the workflow-tool tests

| Fixture | Used for |
| --- | --- |
| `good_tool.cwl` | A valid CommandLineTool that packs cleanly; the happy path for `register_workflow` / `update_workflow`. |
| `fail_pack_yaml_indent.cwl` | `label:` under-indented by one space. |
| `fail_pack_unknown_type.cwl` | `type: Frobnicate`. |
| `fail_pack_missing_run.cwl` | A step runs a file that does not exist. |
| `fail_pack_duplicate_ids.cwl` | Input `sample` declared twice. |

`cwltool --pack` rejects every `fail_pack_*` file, so the local registration
tools must fail before making any API request: nothing uploaded, no workflow,
no version, no deployment.

The server does not parse CWL. A workflow's `inputs` / `outputs` schema is
read from the CWL by the calling model and passed in as tool arguments, so
these fixtures only exercise packing.
