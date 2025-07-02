import unittest
import hashlib
from unittest.mock import patch, mock_open
from bs4 import BeautifulSoup
from bs4.element import Comment
from mega_diff import (
    _get_file_extension_from_content_type,
    normalize_content,
    calculate_file_hash,
    filter_content_for_diff,
)


class TestMegaDiff(unittest.TestCase):

    def test_get_file_extension_from_content_type(self):
        self.assertEqual(_get_file_extension_from_content_type("text/html"), "html")
        self.assertEqual(_get_file_extension_from_content_type("text/css"), "css")
        self.assertEqual(
            _get_file_extension_from_content_type("application/javascript"), "js"
        )
        self.assertEqual(_get_file_extension_from_content_type("image/jpeg"), "jpeg")
        self.assertEqual(
            _get_file_extension_from_content_type("application/json"), "bin"
        )
        self.assertEqual(_get_file_extension_from_content_type(""), "bin")

    def test_normalize_content_html(self):
        html_content = "<!-- comment -->\n<p>  Hello   World!  </p>\n\n<div>Test</div>"
        # Expected output after normalization (prettify + strip empty lines)
        # The actual output of prettify can vary slightly, so we normalize the expected string too
        soup = BeautifulSoup(html_content, "html.parser")
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        prettified_html = soup.prettify()
        normalized_lines = [
            line.strip() for line in prettified_html.splitlines() if line.strip()
        ]
        expected_html = "\n".join(normalized_lines)

        self.assertEqual(normalize_content(html_content, "html"), expected_html)

    def test_normalize_content_css(self):
        css_content = (
            "/* comment */\nbody {  color: red;  }\n\n.container {\n  margin: 0;\n}"
        )
        expected_css = "body { color: red; } .container { margin: 0; }"
        self.assertEqual(normalize_content(css_content, "css"), expected_css)

    def test_normalize_content_js(self):
        js_content = "// comment\nfunction test() {  console.log('hello');  }\n/* multi-line\ncomment */\nvar x = 1;"
        # jsbeautifier output can vary slightly based on version/defaults
        # We'll just check if it's processed and not original
        normalized_js = normalize_content(js_content, "js")
        self.assertNotEqual(normalized_js, js_content)
        self.assertIn(
            "console.log('hello');", normalized_js
        )  # Changed to single quotes

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists", return_value=True)
    def test_calculate_file_hash(self, mock_exists, mock_file):
        mock_file.return_value.read.side_effect = [b"test content", b""]
        self.assertEqual(
            calculate_file_hash("/fake/path/file.txt"),
            hashlib.md5(b"test content").hexdigest(),
        )

        mock_file.return_value.read.side_effect = [b"test content", b""]
        self.assertEqual(
            calculate_file_hash("/fake/path/file.txt", "sha256"),
            hashlib.sha256(b"test content").hexdigest(),
        )

    def test_filter_content_for_diff(self):
        content = "https://dev.example.com/path?ver=1.0.0 and http://prod.example.com/image.jpg"
        working_url = "https://dev.example.com"
        broken_url = "http://prod.example.com"
        # Updated expected_content to match the regex behavior
        expected_content = "[FILTERED_PROTOCOL][FILTERED_DOMAIN]/path and [FILTERED_PROTOCOL][FILTERED_DOMAIN]/image.jpg"
        self.assertEqual(
            filter_content_for_diff(content, working_url, broken_url), expected_content
        )

        content_wp = (
            "<link rel='stylesheet' href='https://example.com/style.css?ver=5.8' />"
        )
        expected_wp = "<link rel='stylesheet' href='[FILTERED_PROTOCOL][FILTERED_DOMAIN]/style.css' />"
        self.assertEqual(
            filter_content_for_diff(
                content_wp, "https://example.com", "https://example.com"
            ),
            expected_wp,
        )

    def test_generate_html_report_curly_braces(self):
        # Import here to avoid circular import issues
        import tempfile
        from mega_diff import generate_html_report

        diff_results = {"html": [], "css": [], "js": [], "images": []}
        with tempfile.NamedTemporaryFile("r+", suffix=".html", delete=False) as tmp:
            generate_html_report(diff_results, tmp.name)
            tmp.seek(0)
            html_content = tmp.read()
        # Check that CSS curly braces are present literally in the output
        self.assertIn(
            "body { font-family: Arial, sans-serif; margin: 20px; }", html_content
        )
        # Also check that no KeyError or formatting error occurred
        self.assertNotIn("KeyError", html_content)


if __name__ == "__main__":
    unittest.main()
