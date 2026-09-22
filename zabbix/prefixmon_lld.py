#!/usr/bin/env python3
import os
import sys
import json
import requests
import ipaddress
from collections import defaultdict

# ================== CONFIG ==================
NETBOX_URL = os.environ.get("NETBOX_URL", "https://netbox.example")
TIMEOUT = 30
TAG = "cloud-subnet"
VRF_NAME = "internet"


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
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
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

def vrf_name_matches(vrf, expected_name):
    if not vrf or not isinstance(vrf, dict):
        return False
    expected = expected_name.casefold()
    for key in ("name", "slug", "display"):
        value = vrf.get(key)
        if value and str(value).casefold() == expected:
            return True
    return False

def get_prefixes():
    """IPv4 prefixes with tag cloud-subnet and VRF internet."""
    prefixes = netbox_get_paginated(
        "ipam/prefixes/",
        params={
            "family": 4,
            "tag": TAG,
        },
    )
    return [p for p in prefixes if vrf_name_matches(p.get("vrf"), VRF_NAME)]

def get_location(prefix_obj):
    scope = prefix_obj.get("scope")
    if not scope or not isinstance(scope, dict):
        return "UNKNOWN"
    return scope.get("name") or scope.get("display") or "UNKNOWN"

def usable_ipv4_total(net, is_pool=False):
    if is_pool:
        return net.num_addresses
    if net.prefixlen < 31:
        return net.num_addresses - 2
    return net.num_addresses


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
        die(f"NetBox API response for ipam/ip-addresses/ is missing 'count' field")
    if not isinstance(count, int):
        die(
            f"NetBox API response for ipam/ip-addresses/ has invalid 'count' field: "
            f"expected integer, got {type(count).__name__}"
        )
    return count

# ================== LLD: prefixes ==================
def prefix_stats():
    result = []

    for p in get_prefixes():
        parsed = parse_ipv4_network(p)
        if parsed is None:
            continue
        net, prefix, is_pool = parsed

        total = usable_ipv4_total(net, is_pool=is_pool)
        location = get_location(p)
        used = get_used_ips(prefix, p.get("vrf"))

        free = max(total - used, 0)
        free_percent = round((free / total) * 100, 2) if total else 0

        result.append({
            "prefix": prefix,
            "location": location,
            "total": total,
            "used": used,
            "free": free,
            "free_percent": free_percent,
        })

    return {"data": result}

# ================== LLD: locations (агрегат) ==================
def location_stats():
    locations = defaultdict(lambda: {"total": 0, "used": 0})

    for p in get_prefixes():
        parsed = parse_ipv4_network(p)
        if parsed is None:
            continue
        net, prefix, is_pool = parsed

        total = usable_ipv4_total(net, is_pool=is_pool)
        location = get_location(p)
        used = get_used_ips(prefix, p.get("vrf"))

        locations[location]["total"] += total
        locations[location]["used"] += used

    result = []
    for loc, s in locations.items():
        total = s["total"]
        used = s["used"]
        free = max(total - used, 0)
        free_percent = round((free / total) * 100, 2) if total else 0

        result.append({
            "location": loc,
            "total": total,
            "used": used,
            "free": free,
            "free_percent": free_percent,
        })

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
