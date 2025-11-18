import argparse
import requests
from urllib.parse import urljoin, urlparse
import os
import hashlib
from bs4 import BeautifulSoup
from bs4.element import Comment
import difflib
import html
import re
import logging
from jsbeautifier import beautify
from deepdiff import DeepDiff

# Constants
CHUNK_SIZE = 8192
DATA_URI_PREVIEW_LENGTH = 100

# Configure logging
logger = logging.getLogger(__name__)


def _get_file_extension_from_content_type(content_type):
    """Determines file extension based on content type."""
    if "html" in content_type:
        return "html"
    elif "css" in content_type:
        return "css"
    elif "javascript" in content_type:
        return "js"
    elif "image" in content_type:
        return content_type.split("/")[-1] if "/" in content_type else "bin"
    return "bin"


def _determine_file_name_and_path(url, base_dir, content_type=None):
    """Determines the appropriate file name and save path for a URL."""
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)
    url_path_dir = parsed_url.path.lstrip("/")

    if file_name and "." in file_name:
        # It's a file, so remove filename from dir path
        url_path_dir = os.path.dirname(url_path_dir)
    elif url_path_dir and not url_path_dir.endswith("/"):
        # It's a directory without trailing slash, add it to treat as directory
        url_path_dir += "/"

    save_dir = os.path.join(base_dir, url_path_dir)
    os.makedirs(save_dir, exist_ok=True)

    if not file_name or file_name.endswith("/"):
        # Assign a default filename based on content type or a generic one
        ext = (
            _get_file_extension_from_content_type(content_type)
            if content_type
            else "bin"
        )
        if ext == "html":
            file_name = "index.html"
        elif ext == "css":
            file_name = "style.css"
        elif ext == "js":
            file_name = "script.js"
        else:
            file_name = f"resource_{hashlib.md5(url.encode()).hexdigest()}.{ext}"

    return os.path.join(save_dir, file_name)


def _fetch_and_save_resource(url, session, base_dir):
    """Fetches a resource and saves it to the specified base directory.

    Args:
        url: The URL of the resource to fetch.
        session: The requests Session object for connection pooling.
        base_dir: The directory where the resource will be saved.

    Returns:
        The file path where the resource was saved, or None if fetch failed.
    """
    try:
        response = session.get(url, stream=True)
        logger.debug("Fetching %s", url)
        response.raise_for_status()
        logger.debug("Status Code for %s: %d", url, response.status_code)

        content_type = response.headers.get("Content-Type", "").lower()
        save_path = _determine_file_name_and_path(url, base_dir, content_type)

        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
        logger.info("Downloaded: %s to %s", url, save_path)
        return save_path
    except requests.exceptions.RequestException as e:
        logger.error("Error fetching %s: %s", url, e)
        return None


def scrape_page(url, output_dir):
    """Scrapes a web page, downloads its resources, and returns paths to downloaded files.

    Args:
        url: The URL of the page to scrape.
        output_dir: The directory where downloaded resources will be stored.

    Returns:
        A dictionary containing paths to downloaded HTML, CSS, JS, and image files.
    """
    logger.info("Scraping %s...", url)
    session = requests.Session()
    downloaded_files = {"html": None, "css": [], "js": [], "images": []}

    url_hostname = urlparse(url).hostname
    page_dir = os.path.join(output_dir, url_hostname)
    os.makedirs(page_dir, exist_ok=True)

    html_path = _fetch_and_save_resource(url, session, page_dir)
    if html_path:
        downloaded_files["html"] = html_path
        with open(html_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        _download_css_files(soup, url, session, page_dir, downloaded_files)
        _download_js_files(soup, url, session, page_dir, downloaded_files)
        _download_image_files(soup, url, session, page_dir, downloaded_files)

    return downloaded_files


def _download_css_files(soup, base_url, session, page_dir, downloaded_files):
    """Finds and downloads CSS files, and images referenced within them."""
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href")
        if href:
            css_url = urljoin(base_url, href)
            css_path = _fetch_and_save_resource(css_url, session, page_dir)
            if css_path:
                downloaded_files["css"].append(css_path)
                _download_images_from_css(
                    css_path, css_url, session, page_dir, downloaded_files
                )


def _download_images_from_css(css_path, css_url, session, page_dir, downloaded_files):
    """Parses a CSS file for image URLs and downloads them.

    Args:
        css_path: Local path to the CSS file.
        css_url: Original URL of the CSS file (for resolving relative URLs).
        session: The requests Session object.
        page_dir: The directory where images will be saved.
        downloaded_files: Dictionary to store downloaded file paths.
    """
    try:
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        css_image_urls = re.findall(r'url(["\\]?(.*?)["\\]?)', css_content)
        for css_img_rel_url in css_image_urls:
            css_img_url = urljoin(css_url, css_img_rel_url)
            img_path = _fetch_and_save_resource(css_img_url, session, page_dir)
            if img_path:
                downloaded_files["images"].append(img_path)
    except Exception as e:
        logger.error("Error parsing CSS for images %s: %s", css_path, e)


def _download_js_files(soup, base_url, session, page_dir, downloaded_files):
    """Finds and downloads JavaScript files."""
    for script in soup.find_all("script", src=True):
        src = script.get("src")
        if src:
            js_url = urljoin(base_url, src)
            js_path = _fetch_and_save_resource(js_url, session, page_dir)
            if js_path:
                downloaded_files["js"].append(js_path)


def _download_image_files(soup, base_url, session, page_dir, downloaded_files):
    """Finds and downloads images from various HTML attributes and inline styles."""
    _download_images_from_img_tags(soup, base_url, session, page_dir, downloaded_files)
    _download_images_from_picture_elements(
        soup, base_url, session, page_dir, downloaded_files
    )
    _download_images_from_inline_styles(
        soup, base_url, session, page_dir, downloaded_files
    )
    _download_svg_sprites(soup, base_url, session, page_dir, downloaded_files)


def _download_images_from_img_tags(soup, base_url, session, page_dir, downloaded_files):
    """Handles image downloads from <img> tags (src, srcset, data-src).

    Args:
        soup: BeautifulSoup object of the HTML document.
        base_url: Base URL for resolving relative URLs.
        session: The requests Session object.
        page_dir: The directory where images will be saved.
        downloaded_files: Dictionary to store downloaded file paths.
    """
    for img in soup.find_all("img"):
        src = img.get("src")
        if src:
            if src.startswith("data:"):
                logger.debug("Found inline data URI image: %s...", src[:50])
                data_uri_name = f"data_uri_image_{len(downloaded_files['images'])}"
                downloaded_files["images"].append(
                    {"type": "data_uri", "name": data_uri_name, "content": src}
                )
            else:
                img_url = urljoin(base_url, src)
                img_path = _fetch_and_save_resource(img_url, session, page_dir)
                if img_path:
                    downloaded_files["images"].append(img_path)

        # Handle srcset attribute for responsive images
        srcset = img.get("srcset")
        if srcset:
            for src_desc in srcset.split(","):
                src_part = src_desc.strip().split()[0]
                if src_part and not src_part.startswith("data:"):
                    full_srcset_url = urljoin(base_url, src_part)
                    img_path = _fetch_and_save_resource(
                        full_srcset_url, session, page_dir
                    )
                    if img_path:
                        downloaded_files["images"].append(img_path)

        # Handle data-src attribute (lazy loading)
        data_src = img.get("data-src")
        if data_src and not data_src.startswith("data:"):
            img_url = urljoin(base_url, data_src)
            img_path = _fetch_and_save_resource(img_url, session, page_dir)
            if img_path:
                downloaded_files["images"].append(img_path)


def _download_images_from_picture_elements(
    soup, base_url, session, page_dir, downloaded_files
):
    """Handles image downloads from <picture> elements."""
    for picture in soup.find_all("picture"):
        for source in picture.find_all("source"):
            srcset = source.get("srcset")
            if srcset:
                for src_desc in srcset.split(","):
                    src_part = src_desc.strip().split()[0]
                    if src_part and not src_part.startswith("data:"):
                        full_url = urljoin(base_url, src_part)
                        img_path = _fetch_and_save_resource(full_url, session, page_dir)
                        if img_path:
                            downloaded_files["images"].append(img_path)


def _download_images_from_inline_styles(
    soup, base_url, session, page_dir, downloaded_files
):
    """Handles image downloads from inline styles (background-image)."""
    for element in soup.find_all(style=True):
        style_content = element.get("style", "")
        bg_image_urls = re.findall(
            r'background-image:\s*url(["\\]?(.*?)["\\]?)',
            style_content,
            re.IGNORECASE,
        )
        for bg_img_url in bg_image_urls:
            if not bg_img_url.startswith("data:"):
                full_bg_url = urljoin(base_url, bg_img_url)
                img_path = _fetch_and_save_resource(full_bg_url, session, page_dir)
                if img_path:
                    downloaded_files["images"].append(img_path)


def _download_svg_sprites(soup, base_url, session, page_dir, downloaded_files):
    """Handles SVG sprite downloads referenced in <use> elements."""
    for use in soup.find_all("use"):
        href = use.get("xlink:href") or use.get("href")
        if href:
            if "#" in href:
                base_url_svg = href.split("#")[0]
                if base_url_svg:
                    svg_url = urljoin(base_url, base_url_svg)
                    svg_path = _fetch_and_save_resource(svg_url, session, page_dir)
                    if svg_path:
                        downloaded_files["images"].append(svg_path)


def normalize_content(content, content_type):
    """Normalizes HTML, CSS, or JS content for readability while ignoring insignificant whitespace."""
    if content_type == "html":
        soup = BeautifulSoup(content, "html.parser")
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        prettified_html = soup.prettify()
        normalized_lines = [
            line.strip() for line in prettified_html.splitlines() if line.strip()
        ]
        return "\n".join(normalized_lines)

    elif content_type == "css":
        # Remove comments and extra whitespace
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        content = re.sub(r"\s+", " ", content).strip()
        return content

    elif content_type == "js":
        # Use jsbeautifier for consistent JS formatting
        return beautify(content)

    return content


def calculate_file_hash(filepath, hash_algorithm="md5"):
    """Calculates the hash of a file.

    Args:
        filepath: Path to the file to hash.
        hash_algorithm: Hash algorithm to use ('md5' or 'sha256').

    Returns:
        The hexadecimal digest of the file hash.
    """
    hasher = hashlib.md5() if hash_algorithm == "md5" else hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def filter_content_for_diff(content, working_url, broken_url):
    """Filters content to ignore specific differences like domain names, protocols, and WP version numbers in URLs.

    Args:
        content: The content string to filter.
        working_url: The URL of the working page.
        broken_url: The URL of the broken page.

    Returns:
        Filtered content with domains, protocols, and version numbers normalized.
    """
    working_hostname = urlparse(working_url).hostname
    broken_hostname = urlparse(broken_url).hostname

    filtered_content = content

    filtered_content = re.sub(r"https?://", "[FILTERED_PROTOCOL]", filtered_content)

    if working_hostname:
        filtered_content = re.sub(
            re.escape(working_hostname), "[FILTERED_DOMAIN]", filtered_content
        )
    if broken_hostname and broken_hostname != working_hostname:
        filtered_content = re.sub(
            re.escape(broken_hostname), "[FILTERED_DOMAIN]", filtered_content
        )

    filtered_content = re.sub(r"\?ver=[0-9.]+", "", filtered_content)

    return filtered_content


def _create_file_map(file_list):
    """Creates a mapping of basenames to file paths.

    Args:
        file_list: List of file paths.

    Returns:
        Dictionary mapping file basenames to their full paths.
    """
    return {os.path.basename(f): f for f in file_list}


def _format_diff_lines(diff_text):
    """Formats diff lines with HTML styling for added, removed, and unchanged lines.

    Args:
        diff_text: The unified diff output as a string.

    Returns:
        HTML-formatted string with colored diff lines.
    """
    formatted_lines = []
    for line in diff_text.splitlines(keepends=False):
        escaped_line_content = html.escape(line)
        if line.startswith("+"):
            formatted_lines.append(
                f'<span class="diff-added">{escaped_line_content}</span>\n'
            )
        elif line.startswith("-"):
            formatted_lines.append(
                f'<span class="diff-removed">{escaped_line_content}</span>\n'
            )
        else:
            formatted_lines.append(
                f'<span class="diff-unchanged">{escaped_line_content}</span>\n'
            )
    return "".join(formatted_lines)


def generate_html_report(diff_results, output_path):
    """Generates an HTML report of the differences.

    Args:
        diff_results: Dictionary containing diff results for HTML, CSS, JS, and images.
        output_path: Path where the HTML report will be saved.
    """
    html_template = _get_report_html_template()

    html_diffs_str = _format_html_diffs(diff_results["html"])
    css_diffs_str = _format_css_diffs(diff_results["css"])
    js_diffs_str = _format_js_diffs(diff_results["js"])
    image_diffs_str = _format_image_diffs(diff_results["images"])

    final_html = html_template.format(
        html_diffs=html_diffs_str,
        css_diffs=css_diffs_str,
        js_diffs=js_diffs_str,
        image_diffs=image_diffs_str,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_html)


def _get_report_html_template():
    """Returns the HTML template for the diff report."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mega Diff Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1, h2 {{ color: #333; }}
            .diff-section {{ margin-bottom: 30px; border: 1px solid #eee; padding: 15px; border-radius: 5px; }}
            .diff-header {{ background-color: #f0f0f0; padding: 10px; margin: -15px -15px 15px -15px; border-bottom: 1px solid #eee; }}
            .diff-content {{ background-color: #f9f9f9; border: 1px solid #ddd; padding: 10px; overflow-x: auto; white-space: pre-wrap; font-family: monospace; }}
            .diff-added {{ background-color: #e6ffe6; color: #008000; }}
            .diff-removed {{ background-color: #ffe6e6; color: #ff0000; }}
            .diff-unchanged {{ color: #333; }}
            .summary-item {{ margin-bottom: 5px; }}
        </style>
    </head>
    <body>
        <h1>Mega Diff Report</h1>

        <div class="diff-section">
            <div class="diff-header"><h2>HTML Differences</h2></div>
            {html_diffs}
        </div>

        <div class="diff-section">
            <div class="diff-header"><h2>CSS Differences</h2></div>
            {css_diffs}
        </div>

        <div class="diff-section">
            <div class="diff-header"><h2>JavaScript Differences</h2></div>
            {js_diffs}
        </div>

        <div class="diff-section">
            <div class="diff-header"><h2>Image Differences</h2></div>
            {image_diffs}
        </div>

    </body>
    </html>
    """


def _format_html_diffs(html_diff_items):
    """Formats HTML diff items for the report.

    Args:
        html_diff_items: List of HTML diff result dictionaries.

    Returns:
        HTML string representing the formatted diffs.
    """
    if not html_diff_items:
        return (
            "<p style='color: red; font-weight: bold;'>"
            "Failed to fetch one or both HTML files. This is usually due to a network error, "
            "SSL certificate issue, or the URL being unreachable. "
            "Check the console output for details. No HTML comparison was performed."
            "</p>"
        )

    result = ""
    for diff_item in html_diff_items:
        if diff_item["type"] == "html-semantic":
            result += (
                f"<div class='summary-item'><h3>HTML Semantic Diff (DeepDiff)</h3>"
                f"<div class='diff-content'><pre>{html.escape(str(diff_item['deepdiff']))}</pre></div>"
            )
            if diff_item["visual"]:
                result += (
                    f"<h4>Visual Diff</h4>"
                    f"<div class='diff-content'>{_format_diff_lines(diff_item['visual'])}</div>"
                )
            result += "</div>"
        elif diff_item["type"] == "html-visual":
            result += (
                f"<div class='summary-item'><h3>HTML Visual Diff</h3>"
                f"<div class='diff-content'>{_format_diff_lines(diff_item['diff'])}</div></div>"
            )
    return result


def _format_css_diffs(css_diff_items):
    """Formats CSS diff items for the report.

    Args:
        css_diff_items: List of CSS diff result dictionaries.

    Returns:
        HTML string representing the formatted diffs.
    """
    if not css_diff_items:
        return "<p>No CSS differences found.</p>"

    result = ""
    for diff_item in css_diff_items:
        if "diff" in diff_item:
            result += (
                f"<div class='summary-item'><h3>CSS File: {diff_item['file']}</h3>"
                f"<div class='diff-content'>{_format_diff_lines(diff_item['diff'])}</div></div>"
            )
        else:
            result += (
                f"<div class='summary-item'><p>CSS File: {diff_item['file']} - "
                f"{diff_item['status']}</p></div>"
            )
    return result


def _format_js_diffs(js_diff_items):
    """Formats JavaScript diff items for the report.

    Args:
        js_diff_items: List of JavaScript diff result dictionaries.

    Returns:
        HTML string representing the formatted diffs.
    """
    if not js_diff_items:
        return "<p>No JavaScript differences found.</p>"

    result = ""
    for diff_item in js_diff_items:
        if "diff" in diff_item:
            result += (
                f"<div class='summary-item'><h3>JavaScript File: {diff_item['file']}</h3>"
                f"<div class='diff-content'>{_format_diff_lines(diff_item['diff'])}</div></div>"
            )
        else:
            result += (
                f"<div class='summary-item'><p>JavaScript File: {diff_item['file']} - "
                f"{diff_item['status']}</p></div>"
            )
    return result


def _format_image_diffs(image_diff_items):
    """Formats image diff items for the report.

    Args:
        image_diff_items: List of image diff result dictionaries.

    Returns:
        HTML string representing the formatted diffs.
    """
    if not image_diff_items:
        return "<p>No image differences found.</p>"

    result = ""
    for diff_item in image_diff_items:
        result += _format_single_image_diff(diff_item)
    return result


def _format_single_image_diff(diff_item):
    """Formats a single image diff item.

    Args:
        diff_item: Dictionary containing image diff information.

    Returns:
        HTML string for this image diff.
    """
    status = diff_item["status"]
    file_name = diff_item["file"]

    if status == "hash mismatch":
        return (
            f"<div class='summary-item'><p style='color: red;'>Image: {file_name} - Hash Mismatch</p>"
            f"<p style='color: #666;'>Working Hash: {diff_item['working_hash']}</p>"
            f"<p style='color: #666;'>Broken Hash: {diff_item['broken_hash']}</p></div>"
        )
    elif status == "identical":
        return f"<div class='summary-item'><p style='color: green;'>Image: {file_name} - Identical</p></div>"
    elif status == "identical (data URI)":
        data_uri = diff_item.get("data_uri", "")
        data_uri_preview = (
            data_uri[:DATA_URI_PREVIEW_LENGTH] + "..."
            if len(data_uri) > DATA_URI_PREVIEW_LENGTH
            else data_uri
        )
        return (
            f"<div class='summary-item'><p style='color: green;'>Image: {file_name} - Identical (data URI)</p>"
            f"<p style='font-size: 12px; color: #666;'>Data URI: {data_uri_preview}</p></div>"
        )
    elif status == "hash mismatch (data URI)":
        return (
            f"<div class='summary-item'><p style='color: red;'>Image: {file_name} - Hash Mismatch (data URI)</p>"
            f"<p style='font-size: 12px; color: #666;'>Working URI: {diff_item.get('working_data_uri', '')}</p>"
            f"<p style='font-size: 12px; color: #666;'>Broken URI: {diff_item.get('broken_data_uri', '')}</p></div>"
        )
    elif "missing" in status:
        return f"<div class='summary-item'><p style='color: orange;'>Image: {file_name} - {status}</p></div>"
    else:
        return f"<div class='summary-item'><p>Image: {file_name} - {status}</p></div>"


def soup_to_dict(soup):
    """Recursively converts a BeautifulSoup element to a dictionary for DeepDiff comparison.

    Args:
        soup: A BeautifulSoup Tag, NavigableString, or string element.

    Returns:
        A dictionary representation of the element with 'tag', 'attrs', and 'children' keys,
        or a string if the input is text content.
    """
    if isinstance(soup, str):
        return soup
    if hasattr(soup, "name") and soup.name is not None:
        return {
            "tag": soup.name,
            "attrs": dict(soup.attrs),
            "children": [
                soup_to_dict(child)
                for child in soup.children
                if getattr(child, "name", None)
                or (isinstance(child, str) and child.strip())
            ],
        }
    elif hasattr(soup, "contents"):
        return [soup_to_dict(child) for child in soup.contents]
    else:
        return str(soup)


def _compare_html(working_files, broken_files, working_url, broken_url, diff_results):
    """Compares HTML content using both semantic (DeepDiff) and visual (unified diff) methods.

    Args:
        working_files: Dictionary containing paths to working page resources.
        broken_files: Dictionary containing paths to broken page resources.
        working_url: URL of the working page.
        broken_url: URL of the broken page.
        diff_results: Dictionary to store comparison results.
    """
    if not (working_files["html"] and broken_files["html"]):
        return

    with open(working_files["html"], "r", encoding="utf-8") as f:
        working_html_content = f.read()
    with open(broken_files["html"], "r", encoding="utf-8") as f:
        broken_html_content = f.read()

    normalized_working_html = normalize_content(working_html_content, "html")
    normalized_broken_html = normalize_content(broken_html_content, "html")

    filtered_working_html = filter_content_for_diff(
        normalized_working_html, working_url, broken_url
    )
    filtered_broken_html = filter_content_for_diff(
        normalized_broken_html, working_url, broken_url
    )

    working_soup = BeautifulSoup(working_html_content, "html.parser")
    broken_soup = BeautifulSoup(broken_html_content, "html.parser")
    working_dict = soup_to_dict(working_soup)
    broken_dict = soup_to_dict(broken_soup)

    deepdiff_result = DeepDiff(working_dict, broken_dict, ignore_order=True)
    if deepdiff_result:
        diff_results["html"].append(
            {
                "type": "html-semantic",
                "deepdiff": deepdiff_result,
                "visual": None,
            }
        )

    html_diff = list(
        difflib.unified_diff(
            filtered_working_html.splitlines(keepends=True),
            filtered_broken_html.splitlines(keepends=True),
            fromfile="working.html",
            tofile="broken.html",
        )
    )

    if html_diff:
        if diff_results["html"] and diff_results["html"][-1]["type"] == "html-semantic":
            diff_results["html"][-1]["visual"] = "".join(html_diff)
        else:
            diff_results["html"].append(
                {"type": "html-visual", "diff": "".join(html_diff)}
            )
            logger.info("HTML Visual Differences Found.")
    elif not deepdiff_result:
        logger.info("No HTML Differences Found.")


def _compare_single_text_file(
    working_path,
    broken_path,
    file_name,
    content_type,
    working_url,
    broken_url,
    results_list,
):
    """Compares a single text file (CSS or JS) between working and broken versions.

    Args:
        working_path: Path to the working version of the file.
        broken_path: Path to the broken version of the file.
        file_name: Name of the file being compared.
        content_type: Type of content ('css' or 'js').
        working_url: URL of the working page.
        broken_url: URL of the broken page.
        results_list: List to append diff results to.
    """
    with open(working_path, "r", encoding="utf-8") as f:
        working_content = f.read()
    with open(broken_path, "r", encoding="utf-8") as f:
        broken_content = f.read()

    normalized_working = normalize_content(working_content, content_type)
    normalized_broken = normalize_content(broken_content, content_type)

    filtered_working = filter_content_for_diff(
        normalized_working, working_url, broken_url
    )
    filtered_broken = filter_content_for_diff(
        normalized_broken, working_url, broken_url
    )

    file_diff = list(
        difflib.unified_diff(
            filtered_working.splitlines(keepends=True),
            filtered_broken.splitlines(keepends=True),
            fromfile=f"working_{file_name}",
            tofile=f"broken_{file_name}",
        )
    )

    if file_diff:
        results_list.append({"file": file_name, "diff": "".join(file_diff)})
        logger.info("  Differences found in %s: %s", content_type.upper(), file_name)
    else:
        logger.info("  No differences found in %s: %s", content_type.upper(), file_name)


def _compare_css_files(
    working_files, broken_files, working_url, broken_url, diff_results
):
    """Compares CSS files between working and broken pages.

    Args:
        working_files: Dictionary containing paths to working page resources.
        broken_files: Dictionary containing paths to broken page resources.
        working_url: URL of the working page.
        broken_url: URL of the broken page.
        diff_results: Dictionary to store comparison results.
    """
    logger.info("Comparing CSS files...")
    working_css_map = _create_file_map(working_files["css"])
    broken_css_map = _create_file_map(broken_files["css"])

    all_css_names = sorted(set(working_css_map.keys()) | set(broken_css_map.keys()))

    for css_name in all_css_names:
        working_css_path = working_css_map.get(css_name)
        broken_css_path = broken_css_map.get(css_name)

        if working_css_path and broken_css_path:
            _compare_single_text_file(
                working_css_path,
                broken_css_path,
                css_name,
                "css",
                working_url,
                broken_url,
                diff_results["css"],
            )
        elif working_css_path:
            diff_results["css"].append(
                {"file": css_name, "status": "missing in broken"}
            )
            logger.info("  CSS file %s is missing in broken.", css_name)
        elif broken_css_path:
            diff_results["css"].append(
                {"file": css_name, "status": "missing in working"}
            )
            logger.info("  CSS file %s is missing in working.", css_name)


def _compare_js_files(
    working_files, broken_files, working_url, broken_url, diff_results
):
    """Compares JavaScript files between working and broken pages.

    Args:
        working_files: Dictionary containing paths to working page resources.
        broken_files: Dictionary containing paths to broken page resources.
        working_url: URL of the working page.
        broken_url: URL of the broken page.
        diff_results: Dictionary to store comparison results.
    """
    logger.info("Comparing JS files...")
    working_js_map = _create_file_map(working_files["js"])
    broken_js_map = _create_file_map(broken_files["js"])

    all_js_names = sorted(set(working_js_map.keys()) | set(broken_js_map.keys()))

    for js_name in all_js_names:
        working_js_path = working_js_map.get(js_name)
        broken_js_path = broken_js_map.get(js_name)

        if working_js_path and broken_js_path:
            _compare_single_text_file(
                working_js_path,
                broken_js_path,
                js_name,
                "js",
                working_url,
                broken_url,
                diff_results["js"],
            )
        elif working_js_path:
            diff_results["js"].append({"file": js_name, "status": "missing in broken"})
            logger.info("  JS file %s is missing in broken.", js_name)
        elif broken_js_path:
            diff_results["js"].append({"file": js_name, "status": "missing in working"})
            logger.info("  JS file %s is missing in working.", js_name)


def _compare_image_files(working_files, broken_files, diff_results):
    """Compares image files (regular and data URIs) between working and broken pages.

    Args:
        working_files: Dictionary containing paths to working page resources.
        broken_files: Dictionary containing paths to broken page resources.
        diff_results: Dictionary to store comparison results.
    """
    logger.info("Comparing Image files...")

    working_regular_images, working_data_uris = _separate_image_types(
        working_files["images"]
    )
    broken_regular_images, broken_data_uris = _separate_image_types(
        broken_files["images"]
    )

    _compare_regular_images(working_regular_images, broken_regular_images, diff_results)
    _compare_data_uri_images(working_data_uris, broken_data_uris, diff_results)


def _separate_image_types(image_list):
    """Separates regular image files from data URI images.

    Args:
        image_list: List of image items (strings for regular files, dicts for data URIs).

    Returns:
        Tuple of (regular_images list, data_uri_images list).
    """
    regular_images = [f for f in image_list if isinstance(f, str)]
    data_uris = [
        f for f in image_list if isinstance(f, dict) and f.get("type") == "data_uri"
    ]
    return regular_images, data_uris


def _compare_regular_images(working_images, broken_images, diff_results):
    """Compares regular image files by hash.

    Args:
        working_images: List of working image file paths.
        broken_images: List of broken image file paths.
        diff_results: Dictionary to store comparison results.
    """
    working_image_map = _create_file_map(working_images)
    broken_image_map = _create_file_map(broken_images)

    working_image_hashes = {
        name: {"path": path, "hash": calculate_file_hash(path)}
        for name, path in working_image_map.items()
    }
    broken_image_hashes = {
        name: {"path": path, "hash": calculate_file_hash(path)}
        for name, path in broken_image_map.items()
    }

    all_image_names = sorted(
        set(working_image_hashes.keys()) | set(broken_image_hashes.keys())
    )

    for img_name in all_image_names:
        working_img_info = working_image_hashes.get(img_name)
        broken_img_info = broken_image_hashes.get(img_name)

        if working_img_info and broken_img_info:
            if working_img_info["hash"] != broken_img_info["hash"]:
                diff_results["images"].append(
                    {
                        "file": img_name,
                        "status": "hash mismatch",
                        "working_hash": working_img_info["hash"],
                        "broken_hash": broken_img_info["hash"],
                    }
                )
                logger.info("  Image hash mismatch for: %s", img_name)
            else:
                diff_results["images"].append({"file": img_name, "status": "identical"})
                logger.info("  Images are identical: %s", img_name)
        elif working_img_info:
            diff_results["images"].append(
                {"file": img_name, "status": "missing in broken"}
            )
            logger.info("  Image missing in broken: %s", img_name)
        elif broken_img_info:
            diff_results["images"].append(
                {"file": img_name, "status": "missing in working"}
            )
            logger.info("  Image missing in working: %s", img_name)


def _compare_data_uri_images(working_data_uris, broken_data_uris, diff_results):
    """Compares data URI images by content.

    Args:
        working_data_uris: List of working data URI image dictionaries.
        broken_data_uris: List of broken data URI image dictionaries.
        diff_results: Dictionary to store comparison results.
    """
    logger.info("Comparing Data URI images...")
    working_data_uri_map = {uri["name"]: uri for uri in working_data_uris}
    broken_data_uri_map = {uri["name"]: uri for uri in broken_data_uris}
    all_data_uri_names = sorted(
        set(working_data_uri_map.keys()) | set(broken_data_uri_map.keys())
    )

    for data_uri_name in all_data_uri_names:
        working_uri = working_data_uri_map.get(data_uri_name)
        broken_uri = broken_data_uri_map.get(data_uri_name)

        if working_uri and broken_uri:
            if working_uri["content"] == broken_uri["content"]:
                diff_results["images"].append(
                    {
                        "file": data_uri_name,
                        "status": "identical (data URI)",
                        "data_uri": working_uri["content"],
                    }
                )
                logger.info("  Data URI Images are identical: %s", data_uri_name)
            else:
                diff_results["images"].append(
                    {
                        "file": data_uri_name,
                        "status": "hash mismatch (data URI)",
                        "working_data_uri": (
                            working_uri["content"][:DATA_URI_PREVIEW_LENGTH] + "..."
                            if len(working_uri["content"]) > DATA_URI_PREVIEW_LENGTH
                            else working_uri["content"]
                        ),
                        "broken_data_uri": (
                            broken_uri["content"][:DATA_URI_PREVIEW_LENGTH] + "..."
                            if len(broken_uri["content"]) > DATA_URI_PREVIEW_LENGTH
                            else broken_uri["content"]
                        ),
                    }
                )
                logger.info("  Data URI Images differ: %s", data_uri_name)
        elif working_uri:
            diff_results["images"].append(
                {
                    "file": data_uri_name,
                    "status": "missing in broken (data URI)",
                    "data_uri": working_uri["content"],
                }
            )
            logger.info("  Data URI Image missing in broken: %s", data_uri_name)
        elif broken_uri:
            diff_results["images"].append(
                {
                    "file": data_uri_name,
                    "status": "missing in working (data URI)",
                    "data_uri": broken_uri["content"],
                }
            )
            logger.info("  Data URI Image missing in working: %s", data_uri_name)


def _setup_logging(verbose=False):
    """Configures logging for the application.

    Args:
        verbose: If True, sets logging level to DEBUG, otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _print_comparison_summary(working_files, broken_files):
    """Prints a summary of downloaded resources.

    Args:
        working_files: Dictionary containing paths to working page resources.
        broken_files: Dictionary containing paths to broken page resources.
    """
    logger.info("--- Comparison Summary ---")
    logger.info("Working HTML: %s", working_files["html"])
    logger.info("Broken HTML: %s", broken_files["html"])
    logger.info("Working CSS files: %d", len(working_files["css"]))
    logger.info("Broken CSS files: %d", len(broken_files["css"]))
    logger.info("Working JS files: %d", len(working_files["js"]))
    logger.info("Broken JS files: %d", len(broken_files["js"]))
    logger.info("Working Image files: %d", len(working_files["images"]))
    logger.info("Broken Image files: %d", len(broken_files["images"]))


def _validate_html_files(working_files, broken_files, working_url, broken_url):
    """Validates that HTML files were successfully fetched.

    Args:
        working_files: Dictionary containing paths to working page resources.
        broken_files: Dictionary containing paths to broken page resources.
        working_url: URL of the working page.
        broken_url: URL of the broken page.

    Returns:
        True if both HTML files exist, False otherwise.
    """
    missing = []
    if not working_files.get("html"):
        missing.append(f"working_url: {working_url}")
    if not broken_files.get("html"):
        missing.append(f"broken_url: {broken_url}")

    if missing:
        logger.error("Failed to fetch the following HTML file(s):")
        for url_label in missing:
            logger.error("  - %s", url_label)
        logger.error("Aborting all diff operations. No report generated.")
        return False
    return True


def main():
    """Main entry point for the mega diff tool."""
    parser = argparse.ArgumentParser(
        description="Compares two web pages comprehensively."
    )
    parser.add_argument("working_url", help="The URL of the working web page.")
    parser.add_argument("broken_url", help="The URL of the broken web page.")
    parser.add_argument(
        "--output",
        default="mega_diff_output",
        help="Output directory for downloaded resources and report.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (debug) logging.",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    os.makedirs(args.output, exist_ok=True)

    logger.info("Fetching resources for working page...")
    working_files = scrape_page(args.working_url, args.output)

    logger.info("Fetching resources for broken page...")
    broken_files = scrape_page(args.broken_url, args.output)

    _print_comparison_summary(working_files, broken_files)

    if not _validate_html_files(
        working_files, broken_files, args.working_url, args.broken_url
    ):
        exit(1)

    diff_results = {"html": [], "css": [], "js": [], "images": []}

    _compare_html(
        working_files, broken_files, args.working_url, args.broken_url, diff_results
    )
    _compare_css_files(
        working_files, broken_files, args.working_url, args.broken_url, diff_results
    )
    _compare_js_files(
        working_files, broken_files, args.working_url, args.broken_url, diff_results
    )
    _compare_image_files(working_files, broken_files, diff_results)

    report_path = os.path.join(args.output, "mega_diff_report.html")
    generate_html_report(diff_results, report_path)
    logger.info("Report generated at: %s", report_path)


if __name__ == "__main__":
    main()
