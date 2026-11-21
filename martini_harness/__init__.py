"""martini_harness: Martini 3 coarse-grained models from SMILES, one molecule per run.

LangGraph decides the order of the steps, LangChain agents make the chemical decisions (mapping, bead types),
and martini_harness.core does every deterministic calculation and check.
"""
__version__ = "0.3.0"
