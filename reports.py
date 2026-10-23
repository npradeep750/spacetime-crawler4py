from collections import Counter, defaultdict

class Report:
    def __init__(self):
        self._unique_pages = set()
        self._unique_page_count = 0

        self._longest_page = 0

        self._word_count = Counter()

        self._subdomains = defaultdict(int)

    def check_unique_page(self, url):
        """Checks if a page is unique and increments it to the count if so."""
        page = url._replace(fragment="").geturl()

        if page not in self._unique_pages:
            self._unique_pages.add(page)
            self._count += 1

    def get_unique_page_count(self):
        """Returns the count of unique pages."""
        return self._unique_page_count

    def check_longest_page(self):
        pass

    def get_longest(self):
        """Returns the page with the most words"""
        return self._longest_page

    def update_words(self, tokens):
        """Takes the tokens from a page and updates the frequency list of words."""
        self._word_count.update(tokens)

    def get_most_common_words(self, amount=50):
        """Returns the {amount} most common words throughout every page crawled. {amount} defaults to 50."""
        return self._word_count.most_common(amount)

    def get_subdomains():
        # should be able to just use seen() set from scraper.py
        pass

    def add_subdomain(self, subdomain):
        self._subdomains[subdomain] += 1