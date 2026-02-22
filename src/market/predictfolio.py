"""Client for scraping data from PredictFolio."""
import requests
from bs4 import BeautifulSoup


class PredictFolioClient:
    """Client for scraping data from PredictFolio."""

    def __init__(self):
        """Initialize the client."""
        self.base_url = "https://predictfolio.com"

    def get_leaderboard(self):
        """Get the leaderboard from PredictFolio."""
        url = f"{self.base_url}/leaderboard"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching leaderboard: {e}")
            return []

        soup = BeautifulSoup(response.content, "html.parser")
        leaderboard = []

        for row in soup.find_all("tr")[1:]:  # Skip header row
            cols = row.find_all("td")
            if len(cols) >= 2:
                rank = cols[0].text.strip()
                address = cols[1].text.strip()
                leaderboard.append({"rank": rank, "address": address})

        return leaderboard
