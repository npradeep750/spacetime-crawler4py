import re
import hashlib
from urllib.parse import urldefrag, urljoin, urlparse, parse_qsl
from collections import Counter
from reports import Report

from bs4 import BeautifulSoup

LINK_TAGS = {"a", "area", "frame", "iframe"}
ALLOWED_DOMAINS = ("ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu")
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_PAGE_BYTE_SIZE = 5 * 1024 * 1024
MIN_NUM_OF_WORDS = 50
MAX_URL_LENGTH = 200
TRAP_QUERY_KEYS = {
    "do", "rev", "rev2[0]", "rev2[1]", "idx", "image", "tab_files", "tab_details",  # DokuWiki
    "action", "version", "format",                                                  # Trac / MoinMoin
    "ical", "outlook-ical", "tribe-bar-date", "eventdisplay",                       # event calendars
    "share", "replytocom",                                                          # WordPress
    "c", "o",                                                                       # Apache dir-listing sorts
}
TRAP_PATH = re.compile(r"/(timeline|changeset|wp-json|feed|calendar|day|week|month)(/|$)", re.I)
DATE = re.compile(r"\d{4}-\d{2}(-\d{2})?")
PATTERN_LIMIT = 10

seen_links = set()
bad_links = set()
simhashes = []
pattern_hits = Counter()
blocked_patterns = set()
pages_processed = 0

report = Report()


def scraper(url, resp):
    global pages_processed
    links = extract_next_links(url, resp)

    pages_processed += 1
    if pages_processed % 100 == 0:
        report.save()
        report.generate_report_file()

    return [link for link in links if is_valid(link)]


def extract_next_links(url, resp):
    # Implementation required.
    # url: the URL that was used to get the page
    # resp.url: the actual url of the page
    # resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    # resp.error: when status is not 200, you can check the error here, if needed.
    # resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
    #         resp.raw_response.url: the url, again
    #         resp.raw_response.content: the content of the page!
    # Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content

    # Queues an unfollowed redirect to run the scrapper on
    raw = getattr(resp, "raw_response", None)
    if getattr(resp, "status", None) in REDIRECT_CODES and raw is not None:
        bad_links.add(url)
        location = raw.headers.get("Location")
        if location:
            try:
                target, _ = urldefrag(urljoin(url, location.strip()))
                return [target]
            except ValueError:
                pass
        return []

    if getattr(resp, "status", None) != 200 or not raw or url in bad_links or url in seen_links:
        bad_links.add(url)
        return []

    # Follows a redirect, final_url is the page we followed
    final_url = url
    if getattr(raw, "history", None) and getattr(raw, "url", None):
        final_url, _ = urldefrag(raw.url)
        if final_url != url:
            seen_links.add(url)
            if not is_valid(final_url):
                return[]

    seen_links.add(final_url)

    content = raw.content or b"" # b"" means an empty string in bytes
    content_type = raw.headers.get("Content-Type", "").lower()
    if (content_type and "html" not in content_type) or not content or len(content) > MAX_PAGE_BYTE_SIZE:
        bad_links.add(final_url)
        return []

    report.check_unique_page(final_url)
    report.check_ics_subdomain(urlparse(final_url))

    tokens = tokenize_response(resp)

    if len(tokens) < MIN_NUM_OF_WORDS:
        record_bad_page(final_url) # still follow links but because the page is low info we ignore its contents
    else:
        if is_near_duplicate(create_simhash(tokens)):
            bad_links.add(final_url)
            record_bad_page(final_url)
            return []
        report.check_longest_page(final_url, tokens)
        report.update_words(remove_stopwords(tokens))

    html = getattr(raw, "text", "")

    soup = BeautifulSoup(html, "html.parser")

    base_tag = soup.find("base", href=True)
    page_url = final_url
    try:
        base_url = urljoin(page_url, base_tag["href"]) if base_tag else page_url
    except ValueError:
        base_url = page_url

    links = set()

    for tag in soup.find_all(LINK_TAGS):
        attr = "src" if tag.name in {"frame", "iframe"} else "href"
        href = tag.get(attr).split('#')[0] if tag.get(attr) else None
        if href and href.strip():
            try:
                absolute_url, _ = urldefrag(urljoin(base_url, href.strip()))
            except ValueError:
                continue
            if is_valid(absolute_url):
                links.add(absolute_url)

    return links

def tokenize_response(resp):
    try:
        soup = BeautifulSoup(resp.raw_response.content, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ").lower().replace("\u2019", "'")
    except (AttributeError, TypeError):
        return []
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)

def load_stopwords(path="stopwords.txt"):
    """Returns a set of all stopwords from the file given (defaulted to stopwords.txt)."""
    with open(path, 'r', encoding="utf-8") as file:
        return {line.strip().lower() for line in file if line.strip()}

STOPWORDS = load_stopwords()

def remove_stopwords(tokens):
    return [token for token in tokens if token not in STOPWORDS]

def create_simhash(tokens):
    v = [0] * 160
    for token, weight in Counter(tokens).items():
        h = int.from_bytes(hashlib.sha1(token.encode("utf-8")).digest(), "big")
        for i in range(160):
            v[i] += weight if (h >> i) & 1 else -weight
    return sum(1 << i for i, total in enumerate(v) if total >= 0)

def similarity(hash1, hash2):
    return 1 - bin(hash1 ^ hash2).count("1") / 160

def is_near_duplicate(simhash, threshold=0.95):
    """Returns if a page matches one stored. If not, it remembers it."""
    for s in simhashes:
        if similarity(simhash, s) >= threshold:
            return True
    simhashes.append(simhash)
    return False

def is_trap(parsed):
    path, query = parsed.path.lower(), parsed.query.lower()
    segments = [seg for seg in path.split("/") if seg]
    if segments and max(Counter(segments).values()) > 2:
        return True
    if any(k.lower() in TRAP_QUERY_KEYS for k, _ in parse_qsl(query, keep_blank_values=True)):
        return True
    if TRAP_PATH.search(path):
        return True
    if DATE.search(query) or ("/event" in path and DATE.search(path)):
        return True
    return False

def url_pattern(parsed):
    path = re.sub(r"\d+", "N", parsed.path.lower())
    keys = sorted(key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
    return (parsed.hostname or "").lower() + path + "?" + "&".join(keys)

def record_bad_page(url):
    """Gets called on near-duplicate or low-info pages. Blocks a URL template after it gets PATTERN_LIMIT amount of them."""
    pattern = url_pattern(urlparse(url))
    pattern_hits[pattern] += 1
    if pattern_hits[pattern] >= PATTERN_LIMIT:
        blocked_patterns.add(pattern)

def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.

    if url in seen_links or url in bad_links:
        return False

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in set(["http", "https"]):
            return False
        if not any(hostname == domain or hostname.endswith("." + domain) for domain in ALLOWED_DOMAINS):
            return False
        if not url.isascii() or len(url) > MAX_URL_LENGTH:
            return False
        if is_trap(parsed) or url_pattern(parsed) in blocked_patterns:
            return False
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower())

    except TypeError:
        print ("TypeError for ", parsed)
        raise
    except ValueError:
        return False