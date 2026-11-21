# Derived searchable text (not authoritative; consult originals for figures and equations)

| file | source | method |
|---|---|---|
| souza2021-article.txt, souza2021-si.txt | original/papers/Souza2021/*.pdf | pdftotext -layout (made before this prepare pass) |
| alessandri2022-article.txt, alessandri2022-si.txt | original/papers/alessandri2022/*.pdf | pdftotext -layout (made before this prepare pass) |
| bible.txt | original/bible/building_block_table.pdf | pdftotext -layout (made before this prepare pass); figure-based PDF, chemical diagrams are lost in text |
| tutorial-page.txt | original/tutorial/page.html | HTML converted to text with Python's re and html modules: script and style blocks removed, a line break after br and block-level end tags, remaining tags removed, entities unescaped, runs of blank lines collapsed. tutorial.pdf has no text layer (image-only), so text comes from the HTML snapshot; figures only in tutorial.pdf |
| mdp/martini_v3.0_prod_single-solute_gmx2026.3.mdp | original/mdp/martini_v3.0_prod.mdp | Adapted copy (user-requested): single tc group, isotropic C-rescale, nstpcouple 5, ns_type removed, 298.15 K. Every change is marked '; ADAPTED'. Validated: grompp -maxwarn 0 (1 expected NOTE) and a 10 ps run on the SDS test system |
| grunewald2022-polyply-article.txt, grunewald2022-polyply-si.txt | original/papers/grunewald2022-polyply/*.pdf | pdftotext -layout |

Page numbers: Souza 2021 SI printed page numbers equal PDF page numbers (checked pages 4-44).
