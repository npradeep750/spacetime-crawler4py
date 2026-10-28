import re
import hashlib
from urllib.parse import urldefrag, urljoin, urlparse
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

seen_links = set()
bad_links = set()
simhashes = []

report = Report()


def scraper(url, resp):
    links = extract_next_links(url, resp)
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

    # if getattr(resp, "status", None) != 200 or not getattr(resp, "raw_response", None) or url in bad_links or url in seen_links:
    #     bad_links.add(url)
    #     return set()

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
    filtered_tokens = remove_stopwords(tokens)
    
    report.check_longest_page(final_url, filtered_tokens)
    report.update_words(filtered_tokens)

    html = getattr(resp.raw_response, "text", "")

    simhash = create_simhash(resp)

    if simhash in simhashes:
        bad_links.add(final_url)
        return set()
    else:
        try:
            sim = max(similarity(simhash, s) for s in simhashes)
            if sim >= 0.95:
                simhashes.append(simhash)
                bad_links.add(final_url)
                return set()
        except ValueError:
            simhashes.append(simhash)
    
    if simhash not in simhashes:
        simhashes.append(simhash)

    soup = BeautifulSoup(html, "html.parser")

    base_tag = soup.find("base", href=True)
    page_url = getattr(resp, "url", None) or final_url
    base_url = urljoin(page_url, base_tag["href"]) if base_tag else page_url

    links = set()

    for tag in soup.find_all(LINK_TAGS):
        attr = "src" if tag.name in {"frame", "iframe"} else "href"
        href = tag.get(attr).split('#')[0] if tag.get(attr) else None
        if href and href.strip():
            absolute_url, _ = urldefrag(urljoin(base_url, href.strip()))
            if is_valid(absolute_url):
                links.add(absolute_url)

    return links

def tokenize_response(resp):
    try:
        soup = BeautifulSoup(resp.raw_response.content, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ").lower()
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

def similarity(hash1, hash2):
    return sum(h1 == h2 for h1, h2 in zip(hash1, hash2)) / 160

def create_simhash(resp):

    tokens = tokenize_response(resp)
    freq = Counter(tokens)

    # report.check_longest_page(resp, tokens)
    # report.update_words(freq)

    v = [0] * 160

    for token, weight in freq.items():
        hash_hex = hashlib.sha1(token.encode('utf-8')).hexdigest()
        binary_str = f"{int(hash_hex, 16):0160b}"

        for i, bit in enumerate(binary_str):
            v[i] += weight if bit == '1' else -weight
    
    return "".join("1" if bit_sum >= 0 else "0" for bit_sum in v)

# def add_subdomain(url):
#     if "ics.uci.edu" not in url:
#         return
#     pattern = 'https?://([^/]+)\.ics\.uci\.edu'
#     match = re.search(pattern, url)
#     if not match:
#         return
#     subdomain_str = match.group(1).lower()
#     if subdomain_str in ('www', ''):
#         return
#     subdomain = 'https://' + subdomain_str + '.ics.uci.edu'
#     report.add_subdomain(subdomain)

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