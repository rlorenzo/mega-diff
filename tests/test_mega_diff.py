import unittest
import hashlib
import tempfile
import os
from unittest.mock import patch, mock_open
from bs4 import BeautifulSoup
from bs4.element import Comment
from mega_diff import (
    _get_file_extension_from_content_type,
    normalize_content,
    calculate_file_hash,
    filter_content_for_diff,
    soup_to_dict,
    _create_file_map,
    _format_diff_lines,
    _compare_single_text_file,
    _separate_image_types,
    _compare_regular_images,
    _compare_data_uri_images,
    DATA_URI_PREVIEW_LENGTH,
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

    def test_html_diff_detects_class_name_difference(self):
        from mega_diff import normalize_content, filter_content_for_diff
        import difflib

        html1 = '<div class="section-intro__body">Hello</div>'
        html2 = '<div class="section-intro-body">Hello</div>'
        norm1 = normalize_content(html1, "html")
        norm2 = normalize_content(html2, "html")
        filtered1 = filter_content_for_diff(norm1, "https://a.com", "https://b.com")
        filtered2 = filter_content_for_diff(norm2, "https://a.com", "https://b.com")
        diff = list(
            difflib.unified_diff(
                filtered1.splitlines(keepends=True),
                filtered2.splitlines(keepends=True),
                fromfile="working.html",
                tofile="broken.html",
            )
        )
        # There should be a diff line showing the class name difference
        diff_str = "".join(diff)
        self.assertIn("section-intro__body", diff_str)
        self.assertIn("section-intro-body", diff_str)

    def test_deepdiff_detects_html_class_name_difference(self):
        """
        Test that DeepDiff detects a difference in class names between two HTML snippets.
        """
        from deepdiff import DeepDiff

        html1 = '<div class="section-intro__body">Hello</div>'
        html2 = '<div class="section-intro-body">Hello</div>'
        soup1 = BeautifulSoup(html1, "html.parser")
        soup2 = BeautifulSoup(html2, "html.parser")
        dict1 = soup_to_dict(soup1.div)
        dict2 = soup_to_dict(soup2.div)
        diff = DeepDiff(dict1, dict2, ignore_order=True)
        # The diff should show a change in the class attribute
        self.assertIn("values_changed", diff)
        self.assertIn("section-intro__body", str(diff))
        self.assertIn("section-intro-body", str(diff))

    def test_deepdiff_detects_nested_html_difference(self):
        """
        Test that DeepDiff detects differences in nested HTML structures and multiple attributes.
        """
        from deepdiff import DeepDiff

        html1 = '<div class="outer" id="main"><span class="inner">Text</span></div>'
        html2 = '<div class="outer" id="main"><span class="inner-modified">Text</span></div>'
        soup1 = BeautifulSoup(html1, "html.parser")
        soup2 = BeautifulSoup(html2, "html.parser")
        dict1 = soup_to_dict(soup1.div)
        dict2 = soup_to_dict(soup2.div)
        diff = DeepDiff(dict1, dict2, ignore_order=True)
        self.assertIn("values_changed", diff)
        self.assertIn("inner", str(diff))
        self.assertIn("inner-modified", str(diff))

    def test_create_file_map_basic(self):
        """Test _create_file_map with basic file list."""
        file_list = ["/path/to/style.css", "/another/path/main.js", "/home/index.html"]
        result = _create_file_map(file_list)
        expected = {
            "style.css": "/path/to/style.css",
            "main.js": "/another/path/main.js",
            "index.html": "/home/index.html",
        }
        self.assertEqual(result, expected)

    def test_create_file_map_empty_list(self):
        """Test _create_file_map with empty list."""
        result = _create_file_map([])
        self.assertEqual(result, {})

    def test_create_file_map_duplicate_basenames(self):
        """Test _create_file_map when duplicate basenames exist (last one wins)."""
        file_list = ["/path1/style.css", "/path2/style.css"]
        result = _create_file_map(file_list)
        # The second path should overwrite the first
        self.assertEqual(result, {"style.css": "/path2/style.css"})

    def test_format_diff_lines_added(self):
        """Test _format_diff_lines correctly formats added lines."""
        diff_text = "+added line"
        result = _format_diff_lines(diff_text)
        self.assertIn('class="diff-added"', result)
        self.assertIn("+added line", result)

    def test_format_diff_lines_removed(self):
        """Test _format_diff_lines correctly formats removed lines."""
        diff_text = "-removed line"
        result = _format_diff_lines(diff_text)
        self.assertIn('class="diff-removed"', result)
        self.assertIn("-removed line", result)

    def test_format_diff_lines_unchanged(self):
        """Test _format_diff_lines correctly formats unchanged lines."""
        diff_text = " unchanged line"
        result = _format_diff_lines(diff_text)
        self.assertIn('class="diff-unchanged"', result)
        self.assertIn(" unchanged line", result)

    def test_format_diff_lines_html_escaping(self):
        """Test _format_diff_lines properly escapes HTML characters."""
        diff_text = "+<script>alert('xss')</script>"
        result = _format_diff_lines(diff_text)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("&lt;/script&gt;", result)
        self.assertNotIn("<script>", result)

    def test_format_diff_lines_multiple_lines(self):
        """Test _format_diff_lines handles multiple lines correctly."""
        diff_text = "+added\n-removed\n unchanged"
        result = _format_diff_lines(diff_text)
        self.assertIn('class="diff-added"', result)
        self.assertIn('class="diff-removed"', result)
        self.assertIn('class="diff-unchanged"', result)

    def test_separate_image_types_mixed(self):
        """Test _separate_image_types correctly separates mixed image types."""
        image_list = [
            "/path/to/image1.jpg",
            {
                "type": "data_uri",
                "name": "data_uri_image_0",
                "content": "data:image/png;base64,ABC",
            },
            "/path/to/image2.png",
            {
                "type": "data_uri",
                "name": "data_uri_image_1",
                "content": "data:image/gif;base64,DEF",
            },
        ]
        regular, data_uris = _separate_image_types(image_list)
        self.assertEqual(len(regular), 2)
        self.assertEqual(len(data_uris), 2)
        self.assertIn("/path/to/image1.jpg", regular)
        self.assertIn("/path/to/image2.png", regular)
        self.assertEqual(data_uris[0]["name"], "data_uri_image_0")
        self.assertEqual(data_uris[1]["name"], "data_uri_image_1")

    def test_separate_image_types_empty(self):
        """Test _separate_image_types with empty list."""
        regular, data_uris = _separate_image_types([])
        self.assertEqual(regular, [])
        self.assertEqual(data_uris, [])

    def test_separate_image_types_only_regular(self):
        """Test _separate_image_types with only regular images."""
        image_list = ["/path/image1.jpg", "/path/image2.png"]
        regular, data_uris = _separate_image_types(image_list)
        self.assertEqual(len(regular), 2)
        self.assertEqual(len(data_uris), 0)

    def test_separate_image_types_only_data_uri(self):
        """Test _separate_image_types with only data URI images."""
        image_list = [
            {"type": "data_uri", "name": "img1", "content": "data:..."},
            {"type": "data_uri", "name": "img2", "content": "data:..."},
        ]
        regular, data_uris = _separate_image_types(image_list)
        self.assertEqual(len(regular), 0)
        self.assertEqual(len(data_uris), 2)

    def test_separate_image_types_ignores_invalid_dicts(self):
        """Test _separate_image_types ignores dictionaries without type='data_uri'."""
        image_list = [
            "/path/image.jpg",
            {"type": "other", "name": "invalid"},
            {"name": "no_type"},
        ]
        regular, data_uris = _separate_image_types(image_list)
        self.assertEqual(len(regular), 1)
        self.assertEqual(len(data_uris), 0)

    def test_compare_single_text_file_with_differences(self):
        """Test _compare_single_text_file detects differences between files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            working_path = os.path.join(tmpdir, "working.css")
            broken_path = os.path.join(tmpdir, "broken.css")

            with open(working_path, "w") as f:
                f.write("body { color: red; }")
            with open(broken_path, "w") as f:
                f.write("body { color: blue; }")

            results_list = []
            _compare_single_text_file(
                working_path,
                broken_path,
                "style.css",
                "css",
                "https://working.com",
                "https://broken.com",
                results_list,
            )

            self.assertEqual(len(results_list), 1)
            self.assertEqual(results_list[0]["file"], "style.css")
            self.assertIn("diff", results_list[0])
            self.assertIn("red", results_list[0]["diff"])
            self.assertIn("blue", results_list[0]["diff"])

    def test_compare_single_text_file_identical(self):
        """Test _compare_single_text_file with identical files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            working_path = os.path.join(tmpdir, "working.css")
            broken_path = os.path.join(tmpdir, "broken.css")

            with open(working_path, "w") as f:
                f.write("body { color: red; }")
            with open(broken_path, "w") as f:
                f.write("body { color: red; }")

            results_list = []
            _compare_single_text_file(
                working_path,
                broken_path,
                "style.css",
                "css",
                "https://working.com",
                "https://broken.com",
                results_list,
            )

            # No difference should be added
            self.assertEqual(len(results_list), 0)

    @patch("mega_diff.calculate_file_hash")
    def test_compare_regular_images_identical(self, mock_hash):
        """Test _compare_regular_images with identical images."""
        mock_hash.return_value = "abc123"
        working_images = ["/path/image.jpg"]
        broken_images = ["/other/image.jpg"]
        diff_results = {"images": []}

        _compare_regular_images(working_images, broken_images, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(diff_results["images"][0]["status"], "identical")

    @patch("mega_diff.calculate_file_hash")
    def test_compare_regular_images_mismatch(self, mock_hash):
        """Test _compare_regular_images with hash mismatch."""
        mock_hash.side_effect = ["abc123", "def456"]
        working_images = ["/path/image.jpg"]
        broken_images = ["/other/image.jpg"]
        diff_results = {"images": []}

        _compare_regular_images(working_images, broken_images, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(diff_results["images"][0]["status"], "hash mismatch")
        self.assertEqual(diff_results["images"][0]["working_hash"], "abc123")
        self.assertEqual(diff_results["images"][0]["broken_hash"], "def456")

    @patch("mega_diff.calculate_file_hash")
    def test_compare_regular_images_missing_in_broken(self, mock_hash):
        """Test _compare_regular_images with image missing in broken."""
        mock_hash.return_value = "abc123"
        working_images = ["/path/image.jpg"]
        broken_images = []
        diff_results = {"images": []}

        _compare_regular_images(working_images, broken_images, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(diff_results["images"][0]["status"], "missing in broken")

    @patch("mega_diff.calculate_file_hash")
    def test_compare_regular_images_missing_in_working(self, mock_hash):
        """Test _compare_regular_images with image missing in working."""
        mock_hash.return_value = "abc123"
        working_images = []
        broken_images = ["/path/image.jpg"]
        diff_results = {"images": []}

        _compare_regular_images(working_images, broken_images, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(diff_results["images"][0]["status"], "missing in working")

    def test_compare_data_uri_images_identical(self):
        """Test _compare_data_uri_images with identical data URIs."""
        working_uris = [{"name": "img1", "content": "data:image/png;base64,ABC123"}]
        broken_uris = [{"name": "img1", "content": "data:image/png;base64,ABC123"}]
        diff_results = {"images": []}

        _compare_data_uri_images(working_uris, broken_uris, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(diff_results["images"][0]["status"], "identical (data URI)")

    def test_compare_data_uri_images_mismatch(self):
        """Test _compare_data_uri_images with content mismatch."""
        working_uris = [{"name": "img1", "content": "data:image/png;base64,ABC"}]
        broken_uris = [{"name": "img1", "content": "data:image/png;base64,DEF"}]
        diff_results = {"images": []}

        _compare_data_uri_images(working_uris, broken_uris, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(
            diff_results["images"][0]["status"], "hash mismatch (data URI)"
        )
        self.assertIn("working_data_uri", diff_results["images"][0])
        self.assertIn("broken_data_uri", diff_results["images"][0])

    def test_compare_data_uri_images_missing_in_broken(self):
        """Test _compare_data_uri_images with URI missing in broken."""
        working_uris = [{"name": "img1", "content": "data:..."}]
        broken_uris = []
        diff_results = {"images": []}

        _compare_data_uri_images(working_uris, broken_uris, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(
            diff_results["images"][0]["status"], "missing in broken (data URI)"
        )

    def test_compare_data_uri_images_missing_in_working(self):
        """Test _compare_data_uri_images with URI missing in working."""
        working_uris = []
        broken_uris = [{"name": "img1", "content": "data:..."}]
        diff_results = {"images": []}

        _compare_data_uri_images(working_uris, broken_uris, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        self.assertEqual(
            diff_results["images"][0]["status"], "missing in working (data URI)"
        )

    def test_compare_data_uri_images_truncates_preview(self):
        """Test _compare_data_uri_images truncates long URIs to DATA_URI_PREVIEW_LENGTH."""
        long_uri = "data:" + "x" * (DATA_URI_PREVIEW_LENGTH + 50)
        working_uris = [{"name": "img1", "content": long_uri}]
        broken_uris = [{"name": "img1", "content": long_uri + "different"}]
        diff_results = {"images": []}

        _compare_data_uri_images(working_uris, broken_uris, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        # The preview should be truncated and have "..." appended
        preview = diff_results["images"][0]["working_data_uri"]
        self.assertEqual(len(preview), DATA_URI_PREVIEW_LENGTH + 3)  # +3 for "..."
        self.assertTrue(preview.endswith("..."))

    def test_compare_data_uri_images_short_uri_not_truncated(self):
        """Test _compare_data_uri_images does not truncate short URIs."""
        short_uri_working = "data:image/png;base64,ABC"
        short_uri_broken = "data:image/png;base64,DEF"
        working_uris = [{"name": "img1", "content": short_uri_working}]
        broken_uris = [{"name": "img1", "content": short_uri_broken}]
        diff_results = {"images": []}

        _compare_data_uri_images(working_uris, broken_uris, diff_results)

        self.assertEqual(len(diff_results["images"]), 1)
        # Short URIs should not have "..." appended
        working_preview = diff_results["images"][0]["working_data_uri"]
        broken_preview = diff_results["images"][0]["broken_data_uri"]
        self.assertEqual(working_preview, short_uri_working)
        self.assertEqual(broken_preview, short_uri_broken)
        self.assertFalse(working_preview.endswith("..."))
        self.assertFalse(broken_preview.endswith("..."))


if __name__ == "__main__":
    unittest.main()
