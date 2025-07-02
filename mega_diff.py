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
from jsbeautifier import beautify


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
    """Fetches a resource and saves it to the specified base directory."""
    try:
        response = session.get(url, stream=True)
        print(f"DEBUG: Fetching {url}")
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        print(f"DEBUG: Status Code for {url}: {response.status_code}")

        content_type = response.headers.get("Content-Type", "").lower()
        save_path = _determine_file_name_and_path(url, base_dir, content_type)

        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Downloaded: {url} to {save_path}")
        return save_path
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None


def scrape_page(url, output_dir):
    """Scrapes a web page, downloads its resources, and returns paths to downloaded files."""
    print(f"Scraping {url}...")
    session = requests.Session()
    downloaded_files = {"html": None, "css": [], "js": [], "images": []}

    # Create a directory for this URL's resources
    url_hostname = urlparse(url).hostname
    page_dir = os.path.join(output_dir, url_hostname)
    os.makedirs(page_dir, exist_ok=True)

    # Fetch HTML
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
    """Parses a CSS file for image URLs and downloads them."""
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
        print(f"Error parsing CSS for images {css_path}: {e}")


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
    """Handles image downloads from <img> tags (src, srcset, data-src)."""
    for img in soup.find_all("img"):
        # Handle src attribute
        src = img.get("src")
        if src:
            if src.startswith("data:"):
                print(f"Found inline data URI image: {src[:50]}...")
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
    """Calculates the hash of a file."""
    hasher = hashlib.md5() if hash_algorithm == "md5" else hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def filter_content_for_diff(content, working_url, broken_url):
    """Filters content to ignore specific differences like domain names, protocols, and WP version numbers in URLs."""
    working_hostname = urlparse(working_url).hostname
    broken_hostname = urlparse(broken_url).hostname

    filtered_content = content

    # Replace protocols
    filtered_content = re.sub(r"https?://", "[FILTERED_PROTOCOL]", filtered_content)

    # Replace hostnames
    if working_hostname:
        filtered_content = re.sub(
            re.escape(working_hostname), "[FILTERED_DOMAIN]", filtered_content
        )
    if broken_hostname and broken_hostname != working_hostname:
        filtered_content = re.sub(
            re.escape(broken_hostname), "[FILTERED_DOMAIN]", filtered_content
        )

    # Remove WordPress version numbers
    filtered_content = re.sub(r"\?ver=[0-9.]+", "", filtered_content)

    return filtered_content


def generate_html_report(diff_results, output_path):
    """Generates an HTML report of the differences."""
    html_content = """
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

    def format_diff_lines(diff_text):
        formatted_lines = []
        for line in diff_text.splitlines(keepends=False):  # Don't keep newlines here
            escaped_line_content = html.escape(line)
            if line.startswith("+"):
                formatted_lines.append(
                    f'<span class="diff-added">{escaped_line_content}</span>\n'
                )  # Add newline back
            elif line.startswith("-"):
                formatted_lines.append(
                    f'<span class="diff-removed">{escaped_line_content}</span>\n'
                )  # Add newline back
            else:
                formatted_lines.append(
                    f'<span class="diff-unchanged">{escaped_line_content}</span>\n'
                )  # Add newline back
        return "".join(formatted_lines)

    html_diffs_str = ""
    if diff_results["html"]:
        for diff_item in diff_results["html"]:
            html_diffs_str += f"<div class='summary-item'><h3>HTML Content Diff</h3><div class='diff-content'>{format_diff_lines(diff_item['diff'])}</div></div>"
    else:
        html_diffs_str = "<p>No HTML differences found.</p>"

    css_diffs_str = ""
    if diff_results["css"]:
        for diff_item in diff_results["css"]:
            if "diff" in diff_item:
                css_diffs_str += f"<div class='summary-item'><h3>CSS File: {diff_item['file']}</h3><div class='diff-content'>{format_diff_lines(diff_item['diff'])}</div></div>"
            else:
                css_diffs_str += f"<div class='summary-item'><p>CSS File: {diff_item['file']} - {diff_item['status']}</p></div>"
    else:
        css_diffs_str = "<p>No CSS differences found.</p>"

    js_diffs_str = ""
    if diff_results["js"]:
        for diff_item in diff_results["js"]:
            if "diff" in diff_item:
                js_diffs_str += f"<div class='summary-item'><h3>JavaScript File: {diff_item['file']}</h3><div class='diff-content'>{format_diff_lines(diff_item['diff'])}</div></div>"
            else:
                js_diffs_str += f"<div class='summary-item'><p>JavaScript File: {diff_item['file']} - {diff_item['status']}</p></div>"
    else:
        js_diffs_str = "<p>No JavaScript differences found.</p>"

    image_diffs_str = ""
    if diff_results["images"]:
        for diff_item in diff_results["images"]:
            if diff_item["status"] == "hash mismatch":
                image_diffs_str += f"<div class='summary-item'><p style='color: red;'>Image: {diff_item['file']} - Hash Mismatch</p>"
                image_diffs_str += f"<p style='color: #666;'>Working Hash: {diff_item['working_hash']}</p>"
                image_diffs_str += f"<p style='color: #666;'>Broken Hash: {diff_item['broken_hash']}</p></div>"
            elif diff_item["status"] == "identical":
                image_diffs_str += f"<div class='summary-item'><p style='color: green;'>Image: {diff_item['file']} - Identical</p></div>"
            elif diff_item["status"] == "identical (data URI)":
                data_uri_preview = (
                    diff_item.get("data_uri", "")[:100] + "..."
                    if len(diff_item.get("data_uri", "")) > 100
                    else diff_item.get("data_uri", "")
                )
                image_diffs_str += f"<div class='summary-item'><p style='color: green;'>Image: {diff_item['file']} - Identical (data URI)</p>"
                image_diffs_str += f"<p style='font-size: 12px; color: #666;'>Data URI: {data_uri_preview}</p></div>"
            elif diff_item["status"] == "hash mismatch (data URI)":
                image_diffs_str += f"<div class='summary-item'><p style='color: red;'>Image: {diff_item['file']} - Hash Mismatch (data URI)</p>"
                image_diffs_str += f"<p style='font-size: 12px; color: #666;'>Working URI: {diff_item.get('working_data_uri', '')}</p>"
                image_diffs_str += f"<p style='font-size: 12px; color: #666;'>Broken URI: {diff_item.get('broken_data_uri', '')}</p></div>"
            elif "missing" in diff_item["status"]:
                color = "orange" if "missing" in diff_item["status"] else "black"
                image_diffs_str += f"<div class='summary-item'><p style='color: {color};'>Image: {diff_item['file']} - {diff_item['status']}</p></div>"
            else:
                image_diffs_str += f"<div class='summary-item'><p>Image: {diff_item['file']} - {diff_item['status']}</p></div>"
    else:
        image_diffs_str = "<p>No image differences found.</p>"

    final_html = html_content.format(
        html_diffs=html_diffs_str,
        css_diffs=css_diffs_str,
        js_diffs=js_diffs_str,
        image_diffs=image_diffs_str,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_html)


def _compare_html(working_files, broken_files, working_url, broken_url, diff_results):
    """Compares HTML content and adds diff to results."""
    if working_files["html"] and broken_files["html"]:
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

        html_diff = list(
            difflib.unified_diff(
                filtered_working_html.splitlines(keepends=True),
                filtered_broken_html.splitlines(keepends=True),
                fromfile="working.html",
                tofile="broken.html",
            )
        )
        if html_diff:
            diff_results["html"].append({"type": "html", "diff": "".join(html_diff)})
            print("\nHTML Differences Found.")
        else:
            print("\nNo HTML Differences Found.")


def _compare_css_files(
    working_files, broken_files, working_url, broken_url, diff_results
):
    """Compares CSS files and adds diffs to results."""
    print("\nComparing CSS files...")
    working_css_map = {os.path.basename(f): f for f in working_files["css"]}
    broken_css_map = {os.path.basename(f): f for f in broken_files["css"]}

    all_css_names = sorted(
        list(set(working_css_map.keys()) | set(broken_css_map.keys()))
    )

    for css_name in all_css_names:
        working_css_path = working_css_map.get(css_name)
        broken_css_path = broken_css_map.get(css_name)

        if working_css_path and broken_css_path:
            with open(working_css_path, "r", encoding="utf-8") as f:
                working_css_content = f.read()
            with open(broken_css_path, "r", encoding="utf-8") as f:
                broken_css_content = f.read()

            normalized_working_css = normalize_content(working_css_content, "css")
            normalized_broken_css = normalize_content(broken_css_content, "css")

            filtered_working_css = filter_content_for_diff(
                normalized_working_css, working_url, broken_url
            )
            filtered_broken_css = filter_content_for_diff(
                normalized_broken_css, working_url, broken_url
            )

            css_diff = list(
                difflib.unified_diff(
                    filtered_working_css.splitlines(keepends=True),
                    filtered_broken_css.splitlines(keepends=True),
                    fromfile=f"working_{css_name}",
                    tofile=f"broken_{css_name}",
                )
            )
            if css_diff:
                diff_results["css"].append(
                    {"file": css_name, "diff": "".join(css_diff)}
                )
                print(f"  Differences found in CSS: {css_name}")
            else:
                print(f"  No differences found in CSS: {css_name}")
        elif working_css_path:
            diff_results["css"].append(
                {"file": css_name, "status": "missing in broken"}
            )
            print(f"  CSS file {css_name} is missing in broken.")
        elif broken_css_path:
            diff_results["css"].append(
                {"file": css_name, "status": "missing in working"}
            )
            print(f"  CSS file {css_name} is missing in working.")


def _compare_js_files(
    working_files, broken_files, working_url, broken_url, diff_results
):
    """Compares JavaScript files and adds diffs to results."""
    print("\nComparing JS files...")
    working_js_map = {os.path.basename(f): f for f in working_files["js"]}
    broken_js_map = {os.path.basename(f): f for f in broken_files["js"]}

    all_js_names = sorted(list(set(working_js_map.keys()) | set(broken_js_map.keys())))

    for js_name in all_js_names:
        working_js_path = working_js_map.get(js_name)
        broken_js_path = broken_js_map.get(js_name)

        if working_js_path and broken_js_path:
            with open(working_js_path, "r", encoding="utf-8") as f:
                working_js_content = f.read()
            with open(broken_js_path, "r", encoding="utf-8") as f:
                broken_js_content = f.read()

            normalized_working_js = normalize_content(working_js_content, "js")
            normalized_broken_js = normalize_content(broken_js_content, "js")

            filtered_working_js = filter_content_for_diff(
                normalized_working_js, working_url, broken_url
            )
            filtered_broken_js = filter_content_for_diff(
                normalized_broken_js, working_url, broken_url
            )

            js_diff = list(
                difflib.unified_diff(
                    filtered_working_js.splitlines(keepends=True),
                    filtered_broken_js.splitlines(keepends=True),
                    fromfile=f"working_{js_name}",
                    tofile=f"broken_{js_name}",
                )
            )
            if js_diff:
                diff_results["js"].append({"file": js_name, "diff": "".join(js_diff)})
                print(f"  Differences found in JS: {js_name}")
            else:
                print(f"  No differences found in JS: {js_name}")
        elif working_js_path:
            diff_results["js"].append({"file": js_name, "status": "missing in broken"})
            print(f"  JS file {js_name} is missing in broken.")
        elif broken_js_path:
            diff_results["js"].append({"file": js_name, "status": "missing in working"})
            print(f"  JS file {js_name} is missing in working.")


def _compare_image_files(working_files, broken_files, diff_results):
    """Compares image files (regular and data URIs) and adds diffs to results."""
    print("\nComparing Image files...")
    # Separate regular files from data URIs
    working_regular_images = [f for f in working_files["images"] if isinstance(f, str)]
    broken_regular_images = [f for f in broken_files["images"] if isinstance(f, str)]
    working_data_uris = [
        f
        for f in working_files["images"]
        if isinstance(f, dict) and f.get("type") == "data_uri"
    ]
    broken_data_uris = [
        f
        for f in broken_files["images"]
        if isinstance(f, dict) and f.get("type") == "data_uri"
    ]

    working_image_map = {os.path.basename(f): f for f in working_regular_images}
    broken_image_map = {os.path.basename(f): f for f in broken_regular_images}

    working_image_hashes = {
        name: {"path": path, "hash": calculate_file_hash(path)}
        for name, path in working_image_map.items()
    }
    broken_image_hashes = {
        name: {"path": path, "hash": calculate_file_hash(path)}
        for name, path in broken_image_map.items()
    }

    all_image_names = sorted(
        list(set(working_image_hashes.keys()) | set(broken_image_hashes.keys()))
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
                print(f"  Image hash mismatch for: {img_name}")
            else:
                diff_results["images"].append({"file": img_name, "status": "identical"})
                print(f"  Images are identical: {img_name}")
        elif working_img_info:
            diff_results["images"].append(
                {"file": img_name, "status": "missing in broken"}
            )
            print(f"  Image missing in broken: {img_name}")
        elif broken_img_info:
            diff_results["images"].append(
                {"file": img_name, "status": "missing in working"}
            )
            print(f"  Image missing in working: {img_name}")

    # Handle data URI images separately
    print("\nComparing Data URI images...")
    working_data_uris = [
        f
        for f in working_files["images"]
        if isinstance(f, dict) and f.get("type") == "data_uri"
    ]
    broken_data_uris = [
        f
        for f in broken_files["images"]
        if isinstance(f, dict) and f.get("type") == "data_uri"
    ]
    working_data_uri_map = {uri["name"]: uri for uri in working_data_uris}
    broken_data_uri_map = {uri["name"]: uri for uri in broken_data_uris}
    all_data_uri_names = sorted(
        list(set(working_data_uri_map.keys()) | set(broken_data_uri_map.keys()))
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
                print(f"  Data URI Images are identical: {data_uri_name}")
            else:
                diff_results["images"].append(
                    {
                        "file": data_uri_name,
                        "status": "hash mismatch (data URI)",
                        "working_data_uri": working_uri["content"][:100] + "...",
                        "broken_data_uri": broken_uri["content"][:100] + "...",
                    }
                )
                print(f"  Data URI Images differ: {data_uri_name}")
        elif working_uri:
            diff_results["images"].append(
                {
                    "file": data_uri_name,
                    "status": "missing in broken (data URI)",
                    "data_uri": working_uri["content"],
                }
            )
            print(f"  Data URI Image missing in broken: {data_uri_name}")
        elif broken_uri:
            diff_results["images"].append(
                {
                    "file": data_uri_name,
                    "status": "missing in working (data URI)",
                    "data_uri": broken_uri["content"],
                }
            )
            print(f"  Data URI Image missing in working: {data_uri_name}")


def main():
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
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    print("Fetching resources for working page...")
    working_files = scrape_page(args.working_url, args.output)

    print("\nFetching resources for broken page...")
    broken_files = scrape_page(args.broken_url, args.output)

    print("\n--- Comparison Summary ---")
    print(f"Working HTML: {working_files['html']}")
    print(f"Broken HTML: {broken_files['html']}")
    print(f"Working CSS files: {len(working_files['css'])}")
    print(f"Broken CSS files: {len(broken_files['css'])}")
    print(f"Working JS files: {len(working_files['js'])}")
    print(f"Broken JS files: {len(broken_files['js'])}")
    print(f"Working Image files: {len(working_files['images'])}")
    print(f"Broken Image files: {len(broken_files['images'])}")

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

    # Generate final HTML report
    report_path = os.path.join(args.output, "mega_diff_report.html")
    generate_html_report(diff_results, report_path)
    print(f"\nReport generated at: {report_path}")


if __name__ == "__main__":
    main()
