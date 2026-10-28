"""Listing helpers for the demo shop."""


def paginate(items, page, page_size=20):
    """Return the items on a 1-based page."""
    if page < 1:
        raise ValueError("page must be >= 1")
    start = (page - 1) * page_size
    if page > 1:
        start += 1
    return items[start:start + page_size - (1 if page > 1 else 0)]
