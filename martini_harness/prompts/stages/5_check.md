## 5. Emit and check

The pipeline emits ITP/GRO, mapping and parameter records, drawing, minimal system TOP, adapted EM/equilibration/test MDPs and dependency manifest (`build`), then solvates, adds counterions and runs EM, equilibration and the smoke test (`test`), then writes validation, manifest and report and freezes `baseline/` (`finalize`). It ensures include ordering, one defaults definition, no duplicate molecule definitions and identical topology/coordinate ordering.

Default to one molecule in compatible Martini water; `test` neutralizes charged molecules with NA or CL. Report missing solvent or GROMACS; never imply execution. Use at most three repair cycles with retained versions and reasons. For stiff or fused molecules, also run the multi-seed check, because one passing run can be chance, and report how many seeds passed. Do not achieve stability through indiscriminate stiffening, freezing flexible groups, suppressing warnings or deleting interactions. If a model fails, report the failing term and bonded rule. A repair changes the mapping or virtual sites, or is recorded as a manual intervention.

Report chemistry checks, numerical execution and physical evaluation separately. Never promote generated provisional models to the reference library automatically.
