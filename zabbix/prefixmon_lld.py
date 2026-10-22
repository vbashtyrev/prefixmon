#!/usr/bin/env python3
import ipaddress
import json
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

# ================== CONFIG ==================
NETBOX_URL = os.environ.get("NETBOX_URL", "https://netbox.example")
TIMEOUT = 30
TAG = "cloud-subnet"
MAX_WORKERS = 8

_thread_local = threading.local()
_site_region_cache = {}
_site_cache_lock = threading.Lock()


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def read_token():
    try:
        with open("/usr/lib/zabbix/externalscripts/.netbox.token") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN") or read_token()
if not NETBOX_TOKEN:
    die("NetBox token not found")

HEADERS = {
    "Authorization": f"Token {NETBOX_TOKEN}",
    "Accept": "application/json",
}


def _get_session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        _thread_local.session = session
    return session


# ================== API ==================
def _api_error_detail(response):
    if response is None:
        return ""
    try:
        body = response.json()
    except json.JSONDecodeError:
        text = (response.text or "").strip()
        return text[:500] if text else ""
    if isinstance(body, dict):
        for key in ("detail", "error", "message"):
            value = body.get(key)
            if value:
                return str(value)
        return str(body)
    return str(body)


def _request_json(url, params=None):
    session = _get_session()
    try:
        response = session.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = _api_error_detail(getattr(exc, "response", None))
        if detail:
            die(f"NetBox API request failed for {url}: {exc} — {detail}")
        die(f"NetBox API request failed for {url}: {exc}")

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        die(f"NetBox API returned invalid JSON for {url}: {exc}")

    if not isinstance(data, dict):
        die(
            f"NetBox API returned unexpected response structure for {url}: "
            f"expected object, got {type(data).__name__}"
        )
    return data


def netbox_get(endpoint, params=None):
    url = f"{NETBOX_URL}/api/{endpoint}"
    return _request_json(url, params=params)


def netbox_get_paginated(endpoint, params=None):
    params = dict(params or {})
    results = []
    url = f"{NETBOX_URL}/api/{endpoint}"

    while url:
        data = _request_json(url, params=params)
        page_results = data.get("results")
        if page_results is None:
            die(f"NetBox API response for {url} is missing 'results' field")
        if not isinstance(page_results, list):
            die(
                f"NetBox API response for {url} has invalid 'results' field: "
                f"expected list, got {type(page_results).__name__}"
            )
        results.extend(page_results)
        url = data.get("next")
        params = None

    return results


def get_prefixes():
    """IPv4 active prefixes with tag cloud-subnet in VRF id 2."""
    return netbox_get_paginated(
        "ipam/prefixes/",
        params={
            "tag": TAG,
            "family": 4,
            "status": "active",
            "vrf_id": 2,
        },
    )


def _region_from_site(site):
    if not site or not isinstance(site, dict):
        return "UNKNOWN"
    region = site.get("region")
    if not region or not isinstance(region, dict):
        return "UNKNOWN"
    return region.get("name") or region.get("display") or "UNKNOWN"


def prefetch_site_regions(prefixes):
    site_ids = set()
    for prefix_obj in prefixes:
        if prefix_obj.get("scope_type") != "dcim.site":
            continue
        scope_id = prefix_obj.get("scope_id")
        if scope_id is not None:
            site_ids.add(scope_id)

    for site_id in site_ids:
        with _site_cache_lock:
            if site_id in _site_region_cache:
                continue
        url = f"{NETBOX_URL}/api/dcim/sites/{site_id}/"
        site = _request_json(url)
        location = _region_from_site(site)
        with _site_cache_lock:
            _site_region_cache[site_id] = location


def get_location(prefix_obj):
    scope_type = prefix_obj.get("scope_type")
    scope_id = prefix_obj.get("scope_id")
    if scope_type != "dcim.site" or scope_id is None:
        return "UNKNOWN"
    with _site_cache_lock:
        if scope_id in _site_region_cache:
            return _site_region_cache[scope_id]
    return "UNKNOWN"


def usable_ipv4_total(net, is_pool=False):
    if is_pool:
        return net.num_addresses
    if net.prefixlen >= 31:
        return net.num_addresses
    return net.num_addresses - 2


def parse_ipv4_network(prefix_obj):
    if not isinstance(prefix_obj, dict):
        die(f"NetBox prefix object is not a mapping: {prefix_obj!r}")

    prefix = prefix_obj.get("prefix")
    if not prefix:
        die(f"NetBox prefix object is missing 'prefix' field: {prefix_obj!r}")

    try:
        net = ipaddress.ip_network(prefix, strict=False)
    except ValueError as exc:
        die(f"Invalid CIDR {prefix}: {exc}")

    if net.version != 4:
        return None
    return net, prefix, bool(prefix_obj.get("is_pool", False))


def get_used_ips(prefix, vrf):
    params = {
        "parent": prefix,
        "limit": 1,
    }
    if vrf:
        if not isinstance(vrf, dict) or vrf.get("id") is None:
            die(
                f"Prefix {prefix} has VRF without id; "
                "cannot count IPs safely (parent filter ignores VRF)"
            )
        params["vrf_id"] = vrf["id"]

    data = netbox_get("ipam/ip-addresses/", params=params)
    count = data.get("count")
    if count is None:
        die("NetBox API response for ipam/ip-addresses/ is missing 'count' field")
    if not isinstance(count, int):
        die(
            "NetBox API response for ipam/ip-addresses/ has invalid 'count' field: "
            f"expected integer, got {type(count).__name__}"
        )
    return count


def _prefix_row(prefix_obj):
    parsed = parse_ipv4_network(prefix_obj)
    if parsed is None:
        return None
    net, prefix, is_pool = parsed

    total = usable_ipv4_total(net, is_pool=is_pool)
    location = get_location(prefix_obj)
    used = get_used_ips(prefix, prefix_obj.get("vrf"))
    free = max(total - used, 0)
    free_percent = round((free / total) * 100, 2) if total else 0

    return {
        "prefix": prefix,
        "location": location,
        "total": total,
        "used": used,
        "free": free,
        "free_percent": free_percent,
    }


# ================== LLD: prefixes ==================
def prefix_stats():
    prefixes = get_prefixes()
    prefetch_site_regions(prefixes)

    rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for row in executor.map(_prefix_row, prefixes):
            if row is not None:
                rows.append(row)

    rows.sort(key=lambda item: (item["location"], item["prefix"]))
    return {"data": rows}


# ================== LLD: locations (aggregate) ==================
def location_stats():
    prefixes = get_prefixes()
    prefetch_site_regions(prefixes)

    locations = defaultdict(lambda: {"total": 0, "used": 0})

    def _accumulate(prefix_obj):
        parsed = parse_ipv4_network(prefix_obj)
        if parsed is None:
            return None
        net, prefix, is_pool = parsed
        total = usable_ipv4_total(net, is_pool=is_pool)
        location = get_location(prefix_obj)
        used = get_used_ips(prefix, prefix_obj.get("vrf"))
        return location, total, used

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for chunk in executor.map(_accumulate, prefixes):
            if chunk is None:
                continue
            location, total, used = chunk
            locations[location]["total"] += total
            locations[location]["used"] += used

    result = []
    for loc, stats in locations.items():
        total = stats["total"]
        used = stats["used"]
        free = max(total - used, 0)
        free_percent = round((free / total) * 100, 2) if total else 0
        result.append(
            {
                "location": loc,
                "total": total,
                "used": used,
                "free": free,
                "free_percent": free_percent,
            }
        )

    result.sort(key=lambda item: item["location"])
    return {"data": result}


# ================== MAIN ==================
def main():
    if len(sys.argv) != 2:
        die("Usage: prefixmon_lld.py [prefixes|locations]")

    mode = sys.argv[1]

    if mode == "prefixes":
        print(json.dumps(prefix_stats(), indent=2))
    elif mode == "locations":
        print(json.dumps(location_stats(), indent=2))
    else:
        die(f"Unknown mode: {mode}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        die(f"unexpected error: {exc}")
