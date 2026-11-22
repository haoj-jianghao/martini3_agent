# Your step: types and charge (stage 3)

The chosen mapping is in the task message, with the evidence per bead prepared by the pipeline: its rung-1
precedents and the table rows that match it (Souza SI Table 24/25; Alessandri 2022 Table 1 for its size), each with the `PATH:LOCATOR` to cite. Start from that
evidence; search further only when it does not settle a bead. Record every bead of the chosen candidate with
`design_bead`, using exactly the atom lists (and weights) of that candidate, with the typing ladder: rung 1
(`source_bead` REF_ID:BEAD of an opened reference; the references the research step opened need no new `design_open`) when a reference bead holds the same fragment,
otherwise rung 2 or 3 with sources. Where the evidence says the precedents disagree on the type, follow the order in
the stage instructions (the most precedents with the same surroundings, then the partition's source as tie-break) and name the rejected types. Record unverified statements and limitations
with `design_note`. When all beads are recorded, call `design_check`; fix what it reports.
Final answer: one line per bead: name, type, member atoms, rung, source.
