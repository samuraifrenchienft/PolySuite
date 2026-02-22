"""Client for scraping data from PolyScope."""
import requests
from bs4 import BeautifulSoup


class PolyScopeClient:
    """Client for scraping data from PolyScope."""

    def __init__(self):
        """Initialize the client."""
        self.base_url = "https://polyscope.xyz"

    def get_smart_traders(self):
        """Get the list of smart traders from PolyScope."""
        url = f"{self.base_url}/smart-traders"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching smart traders: {e}")
            return []

        soup = BeautifulSoup(response.content, "html.parser")
        smart_traders = []

        for row in soup.find_all("tr")[1:]:  # Skip header row
            cols = row.find_all("td")
            if len(cols) >= 2:
                rank = cols[0].text.strip()
                address = cols[1].text.strip()
                smart_traders.append({"rank": rank, "address": address})

        return smart_traders
