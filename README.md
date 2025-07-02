# Mega Diff

Mega Diff is an open source Python tool for deeply comparing two websites, ideal for identifying differences between development and production environments. It generates an HTML report highlighting discrepancies in content, structure, and other aspects of the web pages.

---

## Features

- Compares two given URLs (e.g., a development site and a production site)
- Generates a detailed HTML report of the differences
- Useful for quality assurance and deployment verification
- Helps debug why a page is broken in development but working in production (or vice versa)

## Installation

1. **Clone the repository:**

    ```bash
    git clone https://github.com/rlorenzo/mega-diff.git
    cd mega-diff
    ```

2. **Create a virtual environment (recommended):**

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

**Troubleshooting on macOS:**

If you see warnings about `LibreSSL` or `urllib3` (e.g., `NotOpenSSLWarning`), it's recommended to use a Python installed via Homebrew or pyenv, as these use OpenSSL and are compatible with modern libraries:

- **Homebrew Python:**

  ```bash
  brew install python
  /opt/homebrew/bin/python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

- **pyenv:**

  ```bash
  brew install pyenv
  pyenv install 3.11.9
  pyenv local 3.11.9
  python -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

## Usage

To run the script, execute `mega_diff.py` with the two URLs you want to compare as arguments:

```bash
python mega_diff.py <working_url> <broken_url>
```

- `<working_url>`: The URL of the page that is working (e.g., production)
- `<broken_url>`: The URL of the page that is broken or under development

**Example:**

```bash
python3 mega_diff.py https://prod.example.com https://dev.example.com
```

After execution, an HTML report named `mega_diff_report.html` will be generated in the `mega_diff_output/` directory, detailing the differences found.

## Testing

To run the test suite, use:

```bash
python -m unittest discover tests
```

This will automatically find and run all tests in the `tests/` directory. Make sure to run this command from the project root directory.

## Development

If you want to contribute to this project, please set up the development environment:

1. **Follow the installation steps above** to set up the basic environment.
2. **Install pre-commit hooks** for code quality:

   ```bash
   pre-commit install
   ```

   This will automatically run code formatting (Black) and linting (flake8) before each commit to ensure code quality standards.

3. **Run pre-commit manually** (optional):

   ```bash
   pre-commit run --all-files
   ```

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
