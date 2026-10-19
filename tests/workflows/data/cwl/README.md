# Failing-CWL test fixtures

Deliberately broken CWL for exercising the failure paths of workflow
registration — specifically the `inputs` / `outputs` schema capture that
fills those columns on `workflowversion`.

Every fixture carries its own expectations in a header comment. This file
explains how they are grouped and why the groups differ.

The single rule all of this exists to protect:

> **Schema capture must never fail a registration.** The schema is
> enrichment. A workflow whose parameters could not be read is still a
> workflow that must register and deploy.

So "fail" below means *the schema was not recorded* — not *the command
failed*. Only one group actually exits non-zero, and it does so before
the schema is ever read.

## Group 1 — rejected at pack time (exit 1, nothing created)

| Fixture | Defect |
| --- | --- |
| `fail_pack_yaml_indent.cwl` | `label:` under-indented by one space |
| `fail_pack_unknown_type.cwl` | `type: Frobnicate` |
| `fail_pack_missing_run.cwl` | step runs a file that doesn't exist |
| `fail_pack_duplicate_ids.cwl` | input `sample` declared twice |

`cwltool --pack` rejects these, so `register_ngs360_workflow.sh` dies at
its packing step: **exit 1, no file uploaded, no workflow created, no
version, no deployment.** The schema parser never runs.

These are here to pin down where the boundary is. The parser on purpose
does *not* validate CWL — it records what the document says, so that a
future CWL version introducing a new type still registers rather than
being rejected by us. cwltool is what enforces the CWL spec, and these
four prove the script leans on it instead of duplicating it.

```
./register_ngs360_workflow.sh create-workflow --name t tests/workflows/data/cwl/fail_pack_yaml_indent.cwl
# error: cwltool failed to pack ... ; partial output left at ...
```

## Group 2 — packs fine, schema cannot be recorded (exit 0, columns NULL)

| Fixture | Defect |
| --- | --- |
| `fail_schema_nan_default.cwl` | `default: .nan` on a `float` input |
| `fail_schema_inf_default.cwl` | `default: .inf` on a `float` input |

The interesting group: valid CWL that cwltool packs without complaint.
`.nan` and `.inf` are legal YAML floats, and cwltool writes them into the
packed output as the bare literals `NaN` and `Infinity` — **which JSON
does not define.** Sending such a default to the API would put a
malformed body on the wire and fail the whole version create.

Expected: the parser refuses, prints its reason, and the registration
**completes normally** with both columns NULL.

```
./register_ngs360_workflow.sh create-workflow -y --name t tests/workflows/data/cwl/fail_schema_inf_default.cwl
#   reason: a parameter value is not valid JSON (Out of range float values ...)
# warning: could not read inputs/outputs from ...; version will record none
# ...
# Registered t   <- exit 0
```

Request body omits the keys entirely:

```json
{"definition_uri": "ngs360://<file-id>", "attributes": [...]}
```

`.inf` is the one to care about — "no upper limit" is a reasonable thing
to write by hand, whereas `.nan` usually arrives by accident. If you want
such a workflow's schema recorded, fix the CWL: use a finite sentinel, or
drop the default and make the input optional.

## Group 3 — remote upload path (exit 0, columns NULL)

| Fixture | Defect |
| --- | --- |
| `fail_remote_unpacked.cwl` | valid CWL, but uploaded as YAML instead of packed |
| `fail_remote_not_cwl.json` | valid JSON that is not a CWL process |
| `fail_remote_two_entry_processes.json` | hand-rolled pack: two Workflows, no `#main` |

These bypass `cwltool` entirely — upload the file to NGS360, then
register it by file id. Group 1's protection does not apply here, because
nothing validates what gets uploaded.

```
upload_file(path="tests/workflows/data/cwl/fail_remote_unpacked.cwl", ...)
register_workflow_from_file_id(file_id=<id>, name="t_unpacked")
```

Each returns `inputs_recorded: None`, `outputs_recorded: None`, and an
`io_warning` naming the cause:

```
fail_remote_unpacked.cwl                definition is not JSON ... Expected the
                                        output of 'cwltool --pack <file>.cwl'
fail_remote_not_cwl.json                document has neither '$graph' nor
                                        'inputs'/'outputs'
fail_remote_two_entry_processes.json    cannot identify the entry process in
                                        '$graph': no '#main' and 2 Workflow
                                        entries among ['#alignment', ...]
```

`fail_remote_unpacked.cwl` is the most likely real-world miss: the file is
valid, runnable CWL and the registration succeeds — only the schema is
quietly absent. The warning spells out `cwltool --pack` because that
string is the only signal the user gets.

`fail_remote_two_entry_processes.json` is where refusing beats guessing.
Either entry would yield a real, plausible-looking schema belonging to the
wrong process. Recording nothing is visibly incomplete; recording the
wrong thing is not.

## Group 4 — control (must succeed)

| Fixture | Expectation |
| --- | --- |
| `pass_no_parameters.cwl` | records `inputs: []`, `outputs: []` |

Not a failure case. It's here because the whole set is meaningless
without it: the two DB states must stay distinguishable.

```
[]      the schema was read; this workflow takes no parameters
NULL    the schema was never read — go look at the definition
```

Run it against Group 2 and compare the rows. If a failing fixture ever
writes `[]`, that distinction is gone and a broken upload becomes
indistinguishable from a parameterless workflow — which is exactly the
bug this fixture guards against regressing.

## Notes

- Packing writes `<name>.packed.cwl` next to the source. Group 1 leaves a
  partial one behind on purpose (the error message says where). They are
  build artifacts; don't commit them.
- Group 1 and 2 exercise `register_ngs360_workflow.sh`
  (`WES-Launcher-new`); Group 3 exercises the MCP server's remote tools.
  Groups 1, 2 and 4 also apply to the MCP `register_workflow` tool, which
  packs locally the same way.
- All of these pass `-y` safely. Without it, Group 2 and 3 show
  `inputs/outputs: (could not be read; none will be recorded)` in the
  confirmation block, which is the intended place to notice the problem
  before registering.
