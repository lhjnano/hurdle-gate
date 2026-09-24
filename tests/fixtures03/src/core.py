"""Fixture source exercising every usage-extraction path of the engine."""


_PRINT_CMD = "Page.printToPDF"  # module constant: collected like any literal
_DYNAMIC_EVENT = "executionContextCreated"  # runtime-composed, never a full literal


def navigate(conn, url):
    conn.send("Page.navigate", {"url": url})
    conn.subscribe("Runtime.*")  # wildcard subscription over a whole domain
    note = "page.navigate"  # wrong shape (lowercase domain): never collected
    plain = "hello world"
    glob = "src/**/*.py"
    return note, plain, glob


def dynamic_method(domain, event):
    # Runtime.executionContextCreated is only reachable through this
    # composition, so it must be declared via extra_usage.
    return domain + "." + event


def print_page(conn, spec):
    conn.send(_PRINT_CMD, spec)
    conn.on(_DYNAMIC_EVENT)
