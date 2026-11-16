def page(items, number, size):
    """Items on 1-based page `number` of `size` items each."""
    start = (number - 1) * size
    return items[start:start + size]


def page_count(items, size):
    """How many pages `page` produces for `items`."""
    q = len(items) // size
    r = len(items) % size
    return q + (1 if r else 0)
