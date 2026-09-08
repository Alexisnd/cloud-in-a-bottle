"""Automated WCAG checks for representative Cloud in a Bottle UI pages."""

import socket
from collections.abc import Iterator

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

from compute_space.tests.local_stack import LocalStack
from compute_space.tests.local_stack import complete_setup
from compute_space.tests.local_stack import make_local_stack_config
from compute_space.tests.utils import managed_router

WCAG_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
PUBLIC_PAGES = ["/setup"]
AUTHENTICATED_PAGES = [
    "/dashboard",
    "/add_app",
    "/settings",
    "/system/",
    "/diagnostics/",
    "/terminal/",
    "/docs/",
]


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LocalStack]:
    config = make_local_stack_config(
        data_root_dir=str(tmp_path_factory.mktemp("accessibility")),
        port=_unused_port(),
        zone_name="accessibility",
        default_apps=[],
    )
    local_stack = LocalStack(config=config)
    with managed_router(config):
        yield local_stack


def _scan_page(page: Page, axe: Axe, base_url: str, path: str) -> list[str]:
    target_url = f"{base_url}{path}"
    response = page.goto(target_url, wait_until="load")
    assert response is not None and response.ok, f"{path} returned {response.status if response else 'no response'}"
    assert page.url == target_url, f"{path} redirected to {page.url}"

    if path == "/settings":
        page.wait_for_function(
            """() => !document.getElementById('archive-backend-status').textContent.trim().startsWith('Loading')
              && !document.getElementById('services-status').textContent.trim().startsWith('Loading')
              && document.getElementById('ssh-status').textContent.trim()"""
        )
    elif path == "/system/":
        page.wait_for_function(
            """() => ['storage-usage-chart', 'cpu-usage-chart', 'mem-usage-chart',
                       'swap-usage-chart', 'storage-body', 'ports-body', 'cs-logs']
              .every(id => {
                const text = document.getElementById(id).textContent.trim();
                return text && !text.startsWith('Loading');
              })"""
        )
    elif path == "/diagnostics/":
        page.wait_for_function("() => !document.getElementById('diag-json').textContent.startsWith('Loading')")
    elif path == "/terminal/":
        page.locator(".xterm-screen").wait_for()

    results = axe.run(
        page,
        options={
            "runOnly": {"type": "tag", "values": WCAG_AA_TAGS},
            "resultTypes": ["violations"],
        },
    )
    failures = []
    for violation in results.response["violations"]:
        for node in violation["nodes"]:
            targets = ", ".join(str(target) for target in node["target"])
            summary = node.get("failureSummary", "").replace("\n", " ")
            failures.append(
                f"{path}: {violation['id']} ({violation['impact']}) at {targets}: {violation['help']}. {summary}"
            )
    return failures


def test_owner_ui_has_no_automatically_detectable_wcag_2_2_aa_violations(page: Page, stack: LocalStack) -> None:
    axe = Axe()
    failures = []

    for path in PUBLIC_PAGES:
        failures.extend(_scan_page(page, axe, stack.router_url, path))

    owner = complete_setup(stack)
    failures.extend(_scan_page(page, axe, stack.router_url, "/login"))
    page.context.add_cookies(
        [{"name": cookie.name, "value": cookie.value, "url": stack.router_url} for cookie in owner.cookies]
    )

    for path in AUTHENTICATED_PAGES:
        failures.extend(_scan_page(page, axe, stack.router_url, path))

    assert not failures, "Automatically detectable WCAG 2.2 AA violations:\n" + "\n".join(failures)
