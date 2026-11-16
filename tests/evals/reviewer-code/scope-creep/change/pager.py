def page(items, number, size):
    """Items on 1-based page `number` of `size` items each."""
    start = (number - 1) * size
    return items[start:start + size]


def page_count(items, size, minimum=0):
    """How many pages `page` produces for `items`, but never fewer than `minimum`."""
    return max(minimum, -(-len(items) // size))
