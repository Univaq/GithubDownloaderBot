# Tests

Install the project and its test dependencies with `python -m pip install -e '.[test]'`.
Run the suite with `python -m pytest -q`.

Unit tests cover framework-independent domain rules and application services. Integration tests use temporary SQLite databases and never touch the production database.
