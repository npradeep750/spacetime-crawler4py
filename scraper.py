import re
import hashlib
from urllib.parse import urldefrag, urljoin, urlparse
from collections import Counter
from reports import Report

from bs4 import BeautifulSoup

LINK_TAGS = {"a", "area", "frame", "iframe"}

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

    if getattr(resp, "status", None) != 200 or not getattr(resp, "raw_response", None) or url in bad_links or url in seen_links:
        bad_links.add(url)
        return set()

    seen_links.add(url)

    report.check_unique_page(url)
    report.check_ics_subdomain(urlparse(url))

    tokens = tokenize_response(resp)
    filtered_tokens = remove_stopwords(tokens)
    
    report.check_longest_page(url, filtered_tokens)
    report.update_words(filtered_tokens)

    html = getattr(resp.raw_response, "text", "")

    simhash = create_simhash(resp)

    if simhash in simhashes:
        bad_links.add(url)
        return set()
    else:
        try:
            sim = max(similarity(simhash, s) for s in simhashes)
            if sim >= 0.95:
                simhashes.append(simhash)
                bad_links.add(url)
                return set()
        except ValueError:
            simhashes.append(simhash)
    
    if simhash not in simhashes:
        simhashes.append(simhash)

    soup = BeautifulSoup(html, "html.parser")

    base_tag = soup.find("base", href=True)
    page_url = getattr(resp, "url", None) or url
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
        if parsed.scheme not in set(["http", "https"]):
            return False
        if not (".ics.uci.edu" in parsed.netloc or 
                ".cs.uci.edu" in parsed.netloc or 
                ".informatics.uci.edu" in parsed.netloc or 
                "stat.uci.edu" in parsed.netloc):
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