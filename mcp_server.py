# mcp_server.py mcptools
import sys
import json
import time
import traceback
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="AgenticScrapper")

_last_html: str = ""


def _clean_html(raw_html: str) -> str:
    # extracted into its own function so both fetch paths use identical cleaning
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag_name in ["script", "style", "svg", "nav", "footer", "iframe", "noscript", "head"]:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    return str(soup)


def _fetch_with_requests(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.text


def _fetch_with_selenium(url: str) -> str:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    # webdriver_manager fetches correct chromedriver version automatically
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    try:
        driver.get(url)
        # wait until DOM is fully loaded before doing anything else
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        # fixed short sleep after readyState for JS frameworks to finish rendering
        time.sleep(2)
        return driver.page_source
    finally:
        # always quit — no matter what happens above, no zombie browser processes
        driver.quit()


@mcp.tool()
def fetch_html(url: str, use_selenium: bool = False) -> str:
    global _last_html
    try:
        if use_selenium:
            print(f" Using Selenium for dynamic rendering: {url}", file=sys.stderr)
            raw_html = _fetch_with_selenium(url)
        else:
            print(f" Using requests for static fetch: {url}", file=sys.stderr)
            raw_html = _fetch_with_requests(url)

        cleaned_html = _clean_html(raw_html)
        _last_html = cleaned_html
        print(f" Successfully fetched and cleaned HTML. Length: {len(cleaned_html)} chars", file=sys.stderr)
        return cleaned_html

    except Exception as e:
        error_msg = f"Error: Failed to fetch HTML. Details: {str(e)}"
        print(f" {error_msg}", file=sys.stderr)
        return error_msg


@mcp.tool()
def run_extraction_code(python_code: str) -> str:
    if not _last_html:
        return "Error: No HTML has been fetched yet. Call fetch_html first."
    local_namespace = {
        "html_content": _last_html,
        "BeautifulSoup": BeautifulSoup,
        "extracted_data": None
    }
    try:
        print(" Evaluating dynamically generated extraction script...", file=sys.stderr)
        exec(python_code, {}, local_namespace)
        result_data = local_namespace.get("extracted_data")

        if result_data is None:
            return "Execution completed, but `extracted_data` is None. You must assign your results to the `extracted_data` variable."
        if isinstance(result_data, list) and len(result_data) == 0:
            return "Execution completed, but `extracted_data` is an empty list. Please verify your CSS selectors and logic against the HTML structure."

        return json.dumps(result_data, indent=2)

    except Exception:
        tb_str = traceback.format_exc()
        print(" Execution failed. Returning traceback to the cognitive engine for self-healing.", file=sys.stderr)
        return tb_str


if __name__ == "__main__":
    mcp.run()