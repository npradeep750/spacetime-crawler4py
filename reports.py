from collections import Counter, defaultdict
from urllib.parse import urldefrag

import os
import pickle

class Report:
    def __init__(self):
        self._unique_pages = set()
        self._unique_page_count = 0

        self._longest_page = None
        self._longest_count = 0

        self._word_count = Counter()

        self._ics_subdomains = Counter()
        # self._subdomains = defaultdict(int)

    def check_unique_page(self, url) -> None:
        """Checks if a page is unique and increments it to the count if so."""
        page, _ = urldefrag(url)

        if page not in self._unique_pages:
            self._unique_pages.add(page)
            self._unique_page_count += 1

    def get_unique_page_count(self) -> int:
        """Returns the count of unique pages."""
        return self._unique_page_count

    def check_longest_page(self, page, tokens):
        page_len = len(tokens)
        if page_len > self._longest_count:
            self._longest_count = page_len
            self._longest_page = page

    def get_longest(self):
        """Returns the page with the most words"""
        return self._longest_page

    def update_words(self, tokens):
        """Takes the tokens from a page and updates the frequency list of words."""
        self._word_count.update(tokens)

    def get_most_common_words(self, amount: int = 50) -> list[tuple[str, int]]:
        """Returns the {amount} most common words throughout every page crawled. {amount} defaults to 50."""
        return self._word_count.most_common(amount)

    def check_ics_subdomain(self, page):
        """Takes in a page and increments it to a Counter if it's an ICS subdomain."""
        hostname = page.hostname
        if not hostname:
            return
        hostname = hostname.rstrip(".")
        if hostname.endswith(".ics.uci.edu") or hostname == "ics.uci.edu":
            self._ics_subdomains[hostname] += 1

    def generate_report_file(self, filename: str = "crawl_report.txt") -> None:
        """Writes all collected statistics into a formatted text file."""
        with open(filename, "w", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write("          WEB CRAWLER STATISTICS REPORT          \n")
            f.write("=" * 50 + "\n\n")

            # 1. Unique Pages Count
            f.write(f"Total Unique Pages: {self.get_unique_page_count()}\n\n")

            # 2. Longest Page
            f.write("Longest Page (by word count):\n")
            if self._longest_page:
                f.write(f"  URL: {self._longest_page}\n")
                f.write(f"  Word Count: {self._longest_count}\n")
            else:
                f.write("  N/A\n")
            f.write("\n")

            # 3. ICS Subdomains
            f.write(f"ICS Subdomains (sorted alphabetically): {len(self._ics_subdomains)}\n")
            if self._ics_subdomains:
                for subdomain, count in sorted(self._ics_subdomains.items()):
                    f.write(f"  http://{subdomain}, {count}\n")
            else:
                f.write("  N/A\n")
            f.write("\n")

            # 4. Most Common Words
            f.write("Most Common Words (Top 50):\n")
            common_words = self.get_most_common_words(50)
            if common_words:
                for word, freq in common_words:
                    f.write(f"  {word}: {freq}\n")
            else:
                f.write("  N/A\n")

            f.write("\n" + "=" * 50 + "\n")

    def save(self, filename="report_state.pkl"):
        """Saves current stats to disk so a crash or kill doesn't lose everything."""
        tmp = filename + ".tmp"
        with open(tmp, "wb") as file:
            pickle.dump(self.__dict__, file)
        os.replace(tmp, filename)

    def load(self, filename="report_state.pkl"):
        """Restored stats from a saved run."""
        try:
            with open(filename, "rb") as file:
                self.__dict__.update(pickle.load(file))
        except FileNotFoundError:
            pass