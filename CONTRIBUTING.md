# Contributing

Thanks for taking an interest. Bug reports, real-world test areas and pull requests are all welcome.

1. Fork the repository and create a branch.
2. `pip install -e ".[dev,osm]"`
3. Make your change with tests. `pytest` must pass and `ruff check . && ruff format --check .` must be clean.
4. Open a pull request that explains what changed and why.

If you work in FTTx design and something in the engineering defaults (splitter losses, cable sizes, BOM items) does not match your practice, please open an issue. Field experience is the most useful contribution.
