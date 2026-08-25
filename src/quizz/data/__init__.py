"""The committed corpus, inside the package so an installed wheel carries it.

`vintages/` holds one revision log per series and a `SOURCE.json` naming the publisher, the
retrieval date and both declared windows. Nothing here is fetched at run time and no test
reaches the network: `scripts/capture_vintages.py` is the only code that does, it is run by
hand, and what it writes is committed.
"""
