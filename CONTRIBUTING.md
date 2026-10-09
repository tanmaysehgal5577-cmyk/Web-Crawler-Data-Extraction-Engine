# Contributing to CrawlMind

Thank you for your interest in contributing! CrawlMind is an open-source project designed for learning and demonstrating advanced Python system design.

## Development Environment Setup

1.  **Fork and Clone:**
    ```bash
    git clone https://github.com/yourusername/crawlmind.git
    cd crawlmind
    ```

2.  **Create a Virtual Environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    We use `pip` for dependency management.
    ```bash
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    pip install -e .
    ```

## Quality Standards

We strictly enforce code quality using modern Python tools. Your PR must pass all CI checks.

### 1. Formatting and Linting (`ruff`)
We use `ruff` to replace `flake8`, `black`, and `isort`.
```bash
ruff check .
ruff format .
```

### 2. Static Type Checking (`mypy`)
CrawlMind is fully type-hinted. Run `mypy` to ensure there are no type errors.
```bash
mypy .
```

### 3. Testing (`pytest`)
All new features must include tests. We aim for high test coverage.
```bash
pytest tests/
```
To run tests with coverage:
```bash
pytest --cov=. tests/
```

## Pull Request Process

1.  Create a new branch from `main` (e.g., `feature/awesome-new-thing`).
2.  Write your code, adding type hints and docstrings.
3.  Add tests for your code in the `tests/` directory.
4.  Run `ruff`, `mypy`, and `pytest` locally.
5.  Submit a Pull Request with a clear description of the problem solved or feature added.

## Architecture Guidelines

*   **No Side Effects in Parsers:** The `Parser` module must remain pure and stateless. No network requests or database writes should occur inside `html_parser.py`.
*   **Async Everything (Mostly):** Network requests and database queries must be asynchronous. CPU-bound tasks (like parsing HTML) must be offloaded to `ThreadPoolExecutor` or `ProcessPoolExecutor`.
*   **Handle Errors Gracefully:** Use the custom exceptions defined in `Utilities/exceptions.py`. Do not catch generic `Exception` unless absolutely necessary (and log it if you do).
