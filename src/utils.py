import re

def is_valid_address(address: str) -> bool:
    """Check if a string is a valid Ethereum address."""
    return re.match(r"^0x[a-fA-F0-9]{40}$", address) is not None
