## Rules (read first)

These rules come before everything below. A model built against them is not a result of this method, whatever its checks report.

1. **One molecule per run.** Each model is evidence that an agent applying this method to a molecule it has not seen produces a defensible model. A decision made once and applied to several molecules is not that evidence, and any error in it repeats across the batch. This run is bound to one molecule; its tools work only on its folder.
2. **Record decisions only with the design tools, one decision per call.** The tools derive the index queries from the molecule, show each reference bead by bead, record what you opened, and check what you claim against it. A decision that is not recorded through them is not part of the model, and `build` flags a design record written any other way.
3. **Every citation must support its claim.** Rung 1 means the source bead holds the same atoms; `design_bead` verifies this and copies the type. When no precedent holds the fragment, say so and use rung 2 or 3. An honestly marked provisional type is a valid result; a type attributed to a source that does not contain it is not.
4. **Report what happened.** Blocked, partial and provisional outcomes are acceptable results. An outcome made to look complete is not. Finishing quickly is not a goal; when a rule makes the work slower, the slower path is the method.

## Method

Use the LLM for mapping, bead types and charges. Use deterministic code for bonded terms, graph inspection, geometry, file writing and numerical checks. The agent does not choose bonded terms or their values. Deliver a candidate model or an explicit partial result that says what is unresolved. Never claim physical validation from generated files or short dynamics alone.

## Experiment boundary

Allow RDKit, Python/NumPy/SciPy, generic graph/geometry libraries, drawing, reference search, PDF rendering, GROMACS, and for stage 4 an OPLS-AA topology of the molecule supplied by the user (made by any OPLS engine, with any charge method), or, if none is supplied and `opls_ff_gen_command` is set, that engine. Do not invoke, import, copy decision algorithms from, or use generated output from Auto-Martini, SMartini, SwarmCG, CGCompiler, Martini Mapper, martinize or other automatic CG parameter generators during generation. Generic parsers and deterministic bookkeeping are allowed.

Allow documented reference fragments and analogous published models. For strict holdout tests use a precurated reference subset; do not search a full topology file containing the target. If the target topology has been seen, mark `reference_exposed`; do not call the run blind independent generation. Do not silently clear that flag. General guidelines and bead definitions remain allowed.

Cite every factual claim, chemical decision, and numerical value to a configured reference file or a reproducible calculation in the run. For a file citation, include its path and the source locator, such as a section, page, table, moleculetype, line, or Bible workbook row. Label anything not cited that way, including recalled literature, citations, model names, experimental values and rules of thumb, exactly "agent background knowledge, unverified" wherever it appears (decisions, parameter records, comments, report). Unverified knowledge may suggest what to look for, but it cannot by itself justify a bead type, a mapping or a numerical parameter: such a term is `unresolved`. If a source later confirms or contradicts the statement, cite it and record the correction alongside the original statement. Use `design_note` (`unverified`) to include each statement in the report.

Parameterization is MD-free: stage 4 evaluates conformer energies, minima and Hessians with an OPLS force field and runs no dynamics. Do not run AA MD, Bartender or iterative bonded fitting by default. If explicitly enabled, mark `assisted_refinement` and preserve the baseline. The only dynamics in the workflow are the CG execution checks of the finished model. Never alter the nonbonded interaction matrix or introduce new bead types in this workflow.
