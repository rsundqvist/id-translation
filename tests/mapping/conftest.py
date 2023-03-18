from functools import partialmethod

from id_translation.mapping import Mapper, filter_functions, heuristic_functions, score_functions

Mapper.__init__ = partialmethod(Mapper.__init__, verbose_logging=True)  # type: ignore[assignment]
filter_functions.VERBOSE = True
heuristic_functions.VERBOSE = True
score_functions.VERBOSE = True
