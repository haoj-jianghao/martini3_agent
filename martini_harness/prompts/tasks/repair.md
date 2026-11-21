# Your step: repair (stage 5)

The model failed a check; the failure is in the task message. A repair changes the mapping, virtual sites or a
bead (with `replace=true`), never bonded terms or their values, which stage 4 derives again after your change.
Inspect the run files with `read_run_file` when needed. Record what you changed and why with
`design_note` (manual). When the design is consistent again, call `design_check`.
If no defensible repair exists, say so; the model will be reported as it is.
Final answer: what failed, what you changed, and why.
