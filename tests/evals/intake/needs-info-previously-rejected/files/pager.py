def page(items, number, size):
    """Items on 1-based page `number` of `size` items each."""
    start = (number - 1) * size
    return items[start:start + size]
