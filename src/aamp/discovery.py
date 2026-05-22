"""Discover Axis network audio devices on the local LAN.

Five protocols, run in parallel; results de-duplicated by IP:

1. **mDNS / Bonjour** (preferred per Axis OS 12.1+) — browses the meta-service
   ``_services._dns-sd._udp.local.`` to find every ``_axis-*._tcp.local.`` service
   on the LAN, then browses each. Catches whatever service name audio devices use
   without hardcoding guesses (which is good because Axis doesn't publicly
   document the audio service name).
2. **SSDP** — multicast ``M-SEARCH`` on ``239.255.255.250:1900``. Worked
   by default on AXIS OS < 12.0; off by default after that. Cheap to try.
3. **WS-Discovery** — SOAP-over-UDP ``Probe`` on ``239.255.255.250:3702``.
   Off by default after AXIS OS 12.1, but used to be on. ONVIF-style.
4. **HTTP subnet sweep** — iterate the local /24 and probe each IP for
   ``/axis-cgi/basicdeviceinfo.cgi``. Most reliable fallback: doesn't depend
   on the device advertising at all, only on its web port responding.
   Catches whitelabel/OEM Axis hardware whose NIC has a non-Axis OUI.
5. **ARP sweep** — parses ``arp -a`` on Windows, filters by Axis OUIs, confirms
   each candidate via HTTP probe. Only sees devices in the local ARP cache.

Each method returns a list of :class:`DiscoveredDevice`. The orchestrator
:func:`discover_all` runs them in parallel and merges by IP.
:func:`discover_breakdown` keeps the per-protocol breakdown so you can see
which method found what (useful for tuning, and for ripping out methods
that aren't pulling their weight).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import struct
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Axis identity constants
# ---------------------------------------------------------------------------

# IEEE-registered OUIs for Axis Communications AB. Verified directly against
# the IEEE oui.txt registry (236k+ lines, filtered for "Axis Communications AB"):
#   00-40-8C — registered 1998-04-22
#   AC-CC-8E — registered 2011-08-05
#   B8-A4-4F — registered 2019-03-07
#   E8-27-25 — registered 2023-12-08
# Axis has no MA-M or MA-S blocks. Devices with non-Axis OUIs in this list are
# OEM/whitelabel hardware (e.g. 2N-branded units) or use chipset-vendor MACs —
# the HTTP subnet sweep catches those.
AXIS_OUI_PREFIXES: set[str] = {
    "00:40:8C",
    "AC:CC:8E",
    "B8:A4:4F",
    "E8:27:25",
}

# mDNS-SD meta-service that lists every registered service type on the LAN.
# Browsing this and filtering names starting with "_axis-" auto-discovers
# whatever audio service name Axis devices actually use without us guessing.
MDNS_META_SERVICE = "_services._dns-sd._udp.local."

# Known Axis service-type prefixes worth browsing directly even if the meta
# service doesn't list them (some devices respond to direct queries but don't
# register with the meta service).
AXIS_MDNS_SEED_SERVICES: tuple[str, ...] = (
    "_axis-video._tcp.local.",     # confirmed: every Axis audio device on the test LAN advertised here
    "_axis-audiosite._tcp.local.", # confirmed: audio-specific service, found via meta-service browse 2026-05
    "_axis-nvr._tcp.local.",       # NVRs (per Axis dev docs)
    "_axis-audio._tcp.local.",     # speculative; not seen on test LAN but cheap to try
    "_axis-bws._tcp.local.",       # Bonjour Web Service (referenced in older Axis discovery libs)
    # _http._tcp deliberately omitted — empirical test on 2026-05-21 showed it
    # adds 0 unique devices over the _axis-* services (everything _http catches
    # is already caught by _axis-video) and inflates the source-tag string.
)

# Compiled regex for the AXIS Digest-realm fingerprint. Returned in the
# WWW-Authenticate header of every Axis /axis-cgi/* endpoint when the
# request isn't authenticated. The MAC is the suffix — bonus identity info.
# Example: 'Digest realm="AXIS_ACCC8ED78C7B", nonce="...", algorithm=MD5'
_AXIS_REALM_RE = re.compile(r'realm="AXIS_([0-9A-Fa-f]{12})"')


@dataclass
class DiscoveredDevice:
    """One Axis device found on the LAN."""
    ip: str
    mac: Optional[str] = None
    hostname: Optional[str] = None
    serial: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    source: str = "unknown"   # 'mdns:<svc>' | 'ssdp' | 'ws-discovery' | 'http-sweep' | 'arp' | 'manual'
    txt_record: dict[str, Any] = field(default_factory=dict)
    reachable: Optional[bool] = None
    # Classification — set when we have enough info to decide. See
    # aamp.axis_models for the rules.
    #   'audio'          — confirmed audio endpoint (catalog match)
    #   'audio?'         — heuristic match (model prefix matches a known
    #                      audio family but isn't in the catalog)
    #   'aam-pro-server' — C70xx server appliance (runs AAM Pro)
    #   'camera'         — confirmed non-audio camera/other Axis product
    #   'unknown'        — not enough info yet
    device_class: str = "unknown"
    audio_subtype: Optional[str] = None  # 'speaker' | 'amplifier' | ... | None

    def __str__(self) -> str:
        bits = [self.ip]
        if self.model:
            bits.append(self.model)
        if self.serial:
            bits.append(f"sn={self.serial}")
        if self.firmware_version:
            bits.append(f"fw={self.firmware_version}")
        if self.device_class != "unknown":
            label = self.device_class
            if self.audio_subtype:
                label = f"{label}:{self.audio_subtype}"
            bits.append(f"<{label}>")
        bits.append(f"[{self.source}]")
        return "  ".join(bits)

    def classify(self) -> None:
        """Set ``device_class`` and ``audio_subtype`` from current info.

        Uses (in order of decreasing strength):
          1. mDNS service tags in ``self.source`` — ``_axis-audiosite``
             is an audio-specific service.
          2. The model number (from ``self.model``) via the catalog +
             heuristic in :mod:`aamp.axis_models`.

        Idempotent — call whenever new info arrives (e.g. after auth fills
        in the model).
        """
        from . import axis_models as _am

        # 1. mDNS audio-specific service is a strong audio signal even
        #    before we know the model.
        if "_axis-audiosite" in (self.source or ""):
            self.device_class = "audio"
            if not self.audio_subtype:
                self.audio_subtype = "speaker"   # the service is audio-endpoint specific

        # 2. Model-based classification (overrides if more specific).
        if self.model:
            cls = _am.classify_device(self.model)
            sub = _am.audio_subtype(self.model)
            if cls != "unknown":
                # Don't downgrade "audio" (catalog) to "audio?" (heuristic)
                # if a previous pass already set the strong class.
                if not (self.device_class == "audio" and cls == "audio?"):
                    self.device_class = cls
            if sub:
                self.audio_subtype = sub

    def merge_from(self, other: "DiscoveredDevice") -> None:
        """Fill in missing fields from another sighting of the same IP."""
        for fname in ("mac", "hostname", "serial", "model", "firmware_version"):
            if not getattr(self, fname) and getattr(other, fname):
                setattr(self, fname, getattr(other, fname))
        for k, v in (other.txt_record or {}).items():
            self.txt_record.setdefault(k, v)
        if self.reachable is None and other.reachable is not None:
            self.reachable = other.reachable
        # Compose source: keep all distinct method tags joined with "+".
        # De-dupe — ARP internally calls the http-sweep probe to enrich, so
        # the same tag can arrive twice if we don't filter.
        if other.source:
            existing = set(self.source.split("+")) if self.source else set()
            for tag in other.source.split("+"):
                if tag and tag not in existing:
                    self.source = f"{self.source}+{tag}" if self.source else tag
                    existing.add(tag)
        # Reclassify after merging — additional source tags + model from
        # other may upgrade us from "unknown" to "audio".
        self.classify()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _first_str(d: dict, keys: list[str]) -> Optional[str]:
    """Case-insensitive multi-key lookup. Returns first non-empty value."""
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v:
            return str(v)
    return None


def _normalize_mac(raw: str) -> str:
    return raw.replace("-", ":").upper()


def _is_axis_oui(mac: str) -> bool:
    return mac[:8].upper() in AXIS_OUI_PREFIXES


def _local_subnets() -> list[ipaddress.IPv4Network]:
    """Best-effort guess at local /24 subnets to sweep.

    Uses ``socket.gethostbyname_ex`` (no extra deps). On a multi-NIC host
    this typically returns just the primary IP; users with VLANs should
    pass an explicit subnet list to :func:`discover_http_sweep`.
    """
    out: list[ipaddress.IPv4Network] = []
    try:
        # Trick to get the routable local IP without sending packets: connect
        # a UDP socket to a public address (no data is actually sent until
        # sendto, but the kernel picks an interface).
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 1))
            primary = s.getsockname()[0]
        out.append(ipaddress.ip_network(f"{primary}/24", strict=False))
    except OSError:
        pass
    try:
        # Also enumerate every IP the OS resolves for our hostname.
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            try:
                net = ipaddress.ip_network(f"{ip}/24", strict=False)
                if net not in out:
                    out.append(net)
            except ValueError:
                continue
    except OSError:
        pass
    return out


def _http_identify_axis(ip: str, *, timeout: float = 1.5) -> Optional[DiscoveredDevice]:
    """Probe ``/axis-cgi/basicdeviceinfo.cgi`` on the given IP.

    Positive Axis ID is any of these — in order of strength:
      - **401 with ``WWW-Authenticate: Digest realm="AXIS_<MAC>"``** — the most
        reliable signal. Modern Axis firmware (we saw this on every device on
        the test LAN, OS 12+) returns 401 here, and the realm encodes the
        device's MAC. We extract it as a bonus.
      - **200 with a JSON envelope** carrying ``data.propertyList`` — older
        or unauthenticated-enabled firmware. Fills in model/serial/firmware.

    Used both as the subnet-sweep positive-ID step and to enrich ARP hits.
    """
    import httpx
    url = f"http://{ip}/axis-cgi/basicdeviceinfo.cgi"
    body = {"apiVersion": "1.0", "method": "getAllProperties"}
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, json=body)
    except (httpx.HTTPError, OSError):
        return None

    # Path 1: 401 with the AXIS_<MAC> Digest realm — modern firmware.
    if r.status_code == 401:
        auth_hdr = r.headers.get("www-authenticate", "")
        m = _AXIS_REALM_RE.search(auth_hdr)
        if not m:
            return None
        mac_hex = m.group(1).upper()
        mac = ":".join(mac_hex[i:i+2] for i in range(0, 12, 2))
        return DiscoveredDevice(
            ip=ip,
            mac=mac,
            source="http-sweep",
            reachable=True,
            txt_record={"www_authenticate_realm": f"AXIS_{mac_hex}"},
        )

    # Path 2: 200 with JSON payload — older / unauth-enabled firmware.
    if r.status_code == 200:
        try:
            payload = r.json()
        except ValueError:
            return None
        props = (payload.get("data") or {}).get("propertyList") or {}
        if not props and "apiVersion" not in payload:
            return None
        return DiscoveredDevice(
            ip=ip,
            model=props.get("ProdShortName") or props.get("ProdNbr"),
            serial=props.get("SerialNumber"),
            firmware_version=props.get("Version"),
            source="http-sweep",
            reachable=True,
        )

    return None


# ---------------------------------------------------------------------------
# 1. mDNS / Bonjour (multi-service browse via meta-service)
# ---------------------------------------------------------------------------

def discover_mdns(timeout: float = 5.0) -> list[DiscoveredDevice]:
    """Browse mDNS for every Axis-related service type on the LAN.

    Strategy:
      1. Query the meta-service ``_services._dns-sd._udp.local.`` to learn
         which service types are advertised by anyone on the LAN. Filter
         to ones starting with ``_axis-``.
      2. Also browse a small seed list (``AXIS_MDNS_SEED_SERVICES``) in
         case the meta-service didn't return our target before the timeout.
      3. For ``_http._tcp.local.``, only keep entries whose server name
         contains ``axis`` (otherwise the result set is huge).

    Returns one :class:`DiscoveredDevice` per IP seen. Source string is
    ``mdns:<service-type>`` for traceability.
    """
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError as e:
        raise RuntimeError(
            "zeroconf not installed. pip install zeroconf"
        ) from e

    found: dict[str, DiscoveredDevice] = {}
    discovered_types: set[str] = set()

    class _DeviceListener(ServiceListener):
        def __init__(self, type_label: str) -> None:
            self.type_label = type_label

        def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            try:
                info = zc.get_service_info(type_, name, timeout=2000)
            except Exception:
                return
            if info is None:
                return
            txt: dict[str, Any] = {}
            for k, v in (info.properties or {}).items():
                try:
                    kk = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
                    vv = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v
                    txt[kk] = vv
                except Exception:
                    pass
            server = (info.server or "").rstrip(".")
            # For the generic _http._tcp service, only keep entries that
            # smell like Axis (hostname starts with "axis-" is the strongest
            # signal; TXT record might also identify).
            if type_.startswith("_http.") and "axis" not in server.lower():
                if not any("axis" in str(v).lower() for v in txt.values()):
                    return
            for raw in (info.addresses or []):
                try:
                    ip = socket.inet_ntoa(raw)
                except OSError:
                    continue
                src = f"mdns:{self.type_label.rstrip('.')}"
                d = DiscoveredDevice(
                    ip=ip,
                    hostname=server or None,
                    mac=_first_str(txt, ["macaddress", "mac"]),
                    serial=_first_str(txt, ["serialnumber", "serial"]),
                    model=_first_str(txt, ["model", "modelnumber"]),
                    firmware_version=_first_str(txt, ["firmwareversion", "firmware"]),
                    source=src,
                    txt_record=txt,
                )
                if ip in found:
                    found[ip].merge_from(d)
                else:
                    found[ip] = d

        def update_service(self, zc, type_, name): pass
        def remove_service(self, zc, type_, name): pass

    class _MetaListener(ServiceListener):
        """Listens to the meta service and records any _axis-* types it sees."""
        def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            # `name` here is the service-type string itself (e.g.
            # "_axis-video._tcp.local."). For meta-service entries the name
            # ends with "._tcp.local." or "._udp.local.".
            if name.startswith("_axis-"):
                discovered_types.add(name)

        def update_service(self, zc, type_, name): pass
        def remove_service(self, zc, type_, name): pass

    zc = Zeroconf()
    try:
        # Spin up meta browse and seed browses in parallel, share the time budget.
        ServiceBrowser(zc, MDNS_META_SERVICE, _MetaListener())
        seed_browsers = []
        for svc in AXIS_MDNS_SEED_SERVICES:
            seed_browsers.append(
                ServiceBrowser(zc, svc, _DeviceListener(svc))
            )
        # Let mDNS replies stream in. Halfway through, also kick off browses
        # for any new _axis-* types we discovered via the meta service.
        half = max(0.5, timeout / 2)
        time.sleep(half)
        for svc in sorted(discovered_types):
            if svc in AXIS_MDNS_SEED_SERVICES:
                continue
            ServiceBrowser(zc, svc, _DeviceListener(svc))
        time.sleep(timeout - half)
    finally:
        zc.close()

    return list(found.values())


# ---------------------------------------------------------------------------
# 2. SSDP discovery
# ---------------------------------------------------------------------------

SSDP_MCAST = ("239.255.255.250", 1900)

def discover_ssdp(timeout: float = 3.0) -> list[DiscoveredDevice]:
    """Send ``M-SEARCH * HTTP/1.1`` to the SSDP multicast group.

    Listens for ``timeout`` seconds, parses each HTTP-like response, filters
    for Axis (case-insensitive substring in ``SERVER``, ``USN``, or
    ``ST`` header). Confirms each hit via HTTP probe to fill in model/serial.
    """
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_MCAST[0]}:{SSDP_MCAST[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        "ST: ssdp:all\r\n"
        "USER-AGENT: aamp-discovery/1.0 UPnP/1.1\r\n"
        "\r\n"
    ).encode("ascii")

    found: dict[str, DiscoveredDevice] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        sock.bind(("0.0.0.0", 0))
        sock.sendto(msg, SSDP_MCAST)
        # Send twice — first packet sometimes lost on cold multicast routes.
        time.sleep(0.05)
        sock.sendto(msg, SSDP_MCAST)
        deadline = time.monotonic() + timeout
        sock.settimeout(0.5)
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            ip = addr[0]
            text = data.decode("utf-8", errors="replace")
            headers = _parse_ssdp_headers(text)
            blob = " ".join(headers.values()).lower()
            if "axis" not in blob:
                # Not Axis (or doesn't ID as such). Skip.
                continue
            d = DiscoveredDevice(
                ip=ip,
                hostname=headers.get("server"),
                source="ssdp",
                txt_record=headers,
            )
            # Try to pluck a UUID-style serial out of USN if present.
            usn = headers.get("usn", "")
            m = re.search(r"uuid:([a-f0-9-]+)", usn, re.IGNORECASE)
            if m:
                d.serial = m.group(1)
            found[ip] = d
    finally:
        sock.close()

    # Enrich each via the HTTP probe to fill in model + firmware.
    for ip, d in list(found.items()):
        ident = _http_identify_axis(ip, timeout=1.5)
        if ident is not None:
            d.merge_from(ident)
    return list(found.values())


def _parse_ssdp_headers(text: str) -> dict[str, str]:
    """Parse the headers of an HTTP-style SSDP response into a lowercase dict."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line or line.upper().startswith("HTTP/"):
            continue
        k, _, v = line.partition(":")
        out[k.strip().lower()] = v.strip()
    return out


# ---------------------------------------------------------------------------
# 3. WS-Discovery
# ---------------------------------------------------------------------------

WSD_MCAST = ("239.255.255.250", 3702)

WSD_PROBE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
 <s:Header>
  <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
  <a:MessageID>urn:uuid:{msgid}</a:MessageID>
  <a:To s:mustUnderstand="1">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
 </s:Header>
 <s:Body>
  <d:Probe/>
 </s:Body>
</s:Envelope>"""

def discover_ws_discovery(timeout: float = 4.0) -> list[DiscoveredDevice]:
    """SOAP-over-UDP Probe to the WS-Discovery multicast group.

    Sends an unrestricted Probe (no Types filter) so audio devices and
    cameras both respond. Parses each response's ``XAddrs`` (device service
    URL) and ``Scopes`` (ONVIF-style metadata: manufacturer, model, etc.).
    Filters for Axis by substring match.
    """
    probe = WSD_PROBE_TEMPLATE.format(msgid=uuid.uuid4()).encode("utf-8")
    found: dict[str, DiscoveredDevice] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        sock.bind(("0.0.0.0", 0))
        sock.sendto(probe, WSD_MCAST)
        time.sleep(0.05)
        sock.sendto(probe, WSD_MCAST)
        deadline = time.monotonic() + timeout
        sock.settimeout(0.5)
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(16384)
            except socket.timeout:
                continue
            except OSError:
                break
            ip = addr[0]
            parsed = _parse_wsd_probematch(data)
            if not parsed:
                continue
            blob = (parsed.get("scopes", "") + " " +
                    parsed.get("types", "") + " " +
                    parsed.get("xaddrs", "")).lower()
            if "axis" not in blob:
                continue
            d = DiscoveredDevice(
                ip=ip,
                source="ws-discovery",
                txt_record=parsed,
            )
            # ONVIF scopes embed structured metadata like
            #   onvif://www.onvif.org/manufacturer/AXIS
            #   onvif://www.onvif.org/hardware/Q1656-LE
            #   onvif://www.onvif.org/name/AXIS%20Q1656-LE
            scopes = parsed.get("scopes", "")
            mh = re.search(r"/hardware/([^\s/]+)", scopes)
            if mh:
                d.model = mh.group(1)
            mn = re.search(r"/name/([^\s/]+)", scopes)
            if mn and not d.model:
                from urllib.parse import unquote
                d.model = unquote(mn.group(1))
            found[ip] = d
    finally:
        sock.close()

    for ip, d in list(found.items()):
        ident = _http_identify_axis(ip, timeout=1.5)
        if ident is not None:
            d.merge_from(ident)
    return list(found.values())


def _parse_wsd_probematch(data: bytes) -> Optional[dict[str, str]]:
    """Extract Address/XAddrs/Types/Scopes/MessageID from a ProbeMatch SOAP envelope."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    ns = {
        "s": "http://www.w3.org/2003/05/soap-envelope",
        "a": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
        "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    }
    out: dict[str, str] = {}
    for tag, path in (
        ("address", ".//d:ProbeMatch/a:EndpointReference/a:Address"),
        ("types", ".//d:ProbeMatch/d:Types"),
        ("scopes", ".//d:ProbeMatch/d:Scopes"),
        ("xaddrs", ".//d:ProbeMatch/d:XAddrs"),
        ("messageid", ".//a:MessageID"),
    ):
        el = root.find(path, ns)
        if el is not None and el.text:
            out[tag] = el.text.strip()
    return out or None


# ---------------------------------------------------------------------------
# 4. HTTP subnet sweep
# ---------------------------------------------------------------------------

def discover_http_sweep(
    subnets: Optional[list[str]] = None,
    *,
    timeout: float = 3.0,
    max_workers: int = 64,
) -> list[DiscoveredDevice]:
    """Probe every host in the given (or auto-detected) subnets for Axis.

    For each IP, sends ``POST /axis-cgi/basicdeviceinfo.cgi``. Threaded for
    speed — a /24 sweep with 64 workers and 3s timeout typically finishes
    in roughly the slowest-IP time, since unresponsive hosts dominate.

    Default timeout is 3.0s based on the 2026-05-21 empirical test: at 1s,
    two responsive devices (.105 and .238) were missed because their web
    servers were slow to answer.

    Args:
        subnets: list of CIDRs (e.g. ["10.0.1.0/24"]). Defaults to
            auto-detected local /24s.
        timeout: per-IP HTTP probe timeout in seconds.
        max_workers: thread pool size.
    """
    nets: list[ipaddress.IPv4Network]
    if subnets:
        nets = [ipaddress.ip_network(s, strict=False) for s in subnets]
    else:
        nets = _local_subnets()
    if not nets:
        return []

    targets: list[str] = []
    for net in nets:
        # Skip very large networks — a /16 sweep is 65k IPs.
        if net.num_addresses > 1024:
            continue
        for host in net.hosts():
            targets.append(str(host))
    # De-dup; preserve order.
    seen: set[str] = set()
    unique_targets = [t for t in targets if not (t in seen or seen.add(t))]

    found: list[DiscoveredDevice] = []
    found_lock = threading.Lock()

    def _probe(ip: str) -> None:
        d = _http_identify_axis(ip, timeout=timeout)
        if d is not None:
            with found_lock:
                found.append(d)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_probe, unique_targets))
    return found


# ---------------------------------------------------------------------------
# 5. ARP sweep (Windows-targeted)
# ---------------------------------------------------------------------------

_ARP_LINE_RE = re.compile(
    r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+(\w+)",
)


def _parse_arp_table() -> list[tuple[str, str]]:
    try:
        out = subprocess.run(
            ["arp", "-a"], capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    pairs: list[tuple[str, str]] = []
    for line in out.stdout.splitlines():
        m = _ARP_LINE_RE.match(line)
        if m:
            pairs.append((m.group(1), _normalize_mac(m.group(2))))
    return pairs


def discover_arp_sweep(probe_http: bool = True) -> list[DiscoveredDevice]:
    """Find Axis devices in the local ARP cache via Axis OUI filtering.

    With ``probe_http=True``, each hit is enriched (and confirmed) via the
    HTTP basicdeviceinfo probe.
    """
    out: list[DiscoveredDevice] = []
    for ip, mac in _parse_arp_table():
        if not _is_axis_oui(mac):
            continue
        d = DiscoveredDevice(ip=ip, mac=mac, source="arp")
        if probe_http:
            ident = _http_identify_axis(ip)
            if ident is not None:
                d.merge_from(ident)
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

DISCOVERY_METHODS: dict[str, Callable[..., list[DiscoveredDevice]]] = {
    "mdns": discover_mdns,
    "ssdp": discover_ssdp,
    "ws-discovery": discover_ws_discovery,
    "http-sweep": discover_http_sweep,
    "arp": discover_arp_sweep,
}

# Methods that are productive on modern firmware (AXIS OS 12.1+). The first
# empirical run on the test LAN (2026-05-21) showed:
#   mdns: 9/9 in 11s    — workhorse
#   http-sweep: 5/9 in 51s — also harvests MAC from AXIS_<MAC> realm
#   arp: 7/9 in 51s     — all 3 modern Axis OUIs represented in real fleet
#   ssdp: 0/9          — off by default in AXIS OS 12+
#   ws-discovery: 0/9   — off by default in AXIS OS 12.1+
DEFAULT_METHODS: tuple[str, ...] = ("mdns", "http-sweep", "arp")
LEGACY_METHODS: tuple[str, ...] = ("ssdp", "ws-discovery")


@dataclass
class DiscoveryBreakdown:
    """Per-protocol view of one discovery run."""
    by_method: dict[str, list[DiscoveredDevice]] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    merged: list[DiscoveredDevice] = field(default_factory=list)


def discover_breakdown(
    *,
    methods: Optional[list[str]] = None,
    mdns_timeout: float = 5.0,
    ssdp_timeout: float = 3.0,
    wsd_timeout: float = 4.0,
    http_sweep_subnets: Optional[list[str]] = None,
    http_sweep_timeout: float = 1.0,
    arp_probe_http: bool = True,
) -> DiscoveryBreakdown:
    """Run every (or specified) discovery method in parallel; keep per-method results.

    Useful for empirically testing which protocols actually find devices on
    a given network. Returns a :class:`DiscoveryBreakdown` with per-method
    device lists + wall-clock timings + any exceptions raised.
    """
    selected = methods or list(DISCOVERY_METHODS.keys())
    kwargs_per: dict[str, dict[str, Any]] = {
        "mdns": {"timeout": mdns_timeout},
        "ssdp": {"timeout": ssdp_timeout},
        "ws-discovery": {"timeout": wsd_timeout},
        "http-sweep": {"subnets": http_sweep_subnets, "timeout": http_sweep_timeout},
        "arp": {"probe_http": arp_probe_http},
    }

    bd = DiscoveryBreakdown()

    def _run(name: str) -> tuple[str, list[DiscoveredDevice], float, Optional[str]]:
        fn = DISCOVERY_METHODS[name]
        kw = kwargs_per.get(name, {})
        t0 = time.monotonic()
        try:
            res = fn(**kw)
            # Apply classification immediately so per-method results are
            # already labeled when callers inspect ``bd.by_method``.
            for d in res:
                d.classify()
            return name, res, time.monotonic() - t0, None
        except Exception as e:
            return name, [], time.monotonic() - t0, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=len(selected)) as ex:
        futures = [ex.submit(_run, name) for name in selected]
        for fut in as_completed(futures):
            name, devs, dt, err = fut.result()
            bd.by_method[name] = devs
            bd.timings[name] = dt
            if err:
                bd.errors[name] = err

    # Merge into one IP-keyed list — first sighting wins for the source tag,
    # subsequent ones contribute via merge_from().
    merged: dict[str, DiscoveredDevice] = {}
    # Order matters: prefer mdns first, then ssdp, ws-discovery, http-sweep, arp.
    order = ("mdns", "ssdp", "ws-discovery", "http-sweep", "arp")
    for name in [*order, *[n for n in bd.by_method if n not in order]]:
        for d in bd.by_method.get(name, []):
            if d.ip in merged:
                merged[d.ip].merge_from(d)
            else:
                merged[d.ip] = replace(d)
    bd.merged = list(merged.values())
    return bd


def discover_all(
    *,
    prefer_mdns: bool = True,      # kept for backward compat; no longer changes behavior
    mdns_timeout: float = 5.0,
    probe_http_on_arp: bool = True,
    include_legacy: bool = False,
    mdns_only: bool = False,
) -> list[DiscoveredDevice]:
    """Run the productive discovery methods in parallel and return merged results.

    By default runs the three methods that produced results on modern Axis
    firmware: ``mdns`` + ``http-sweep`` + ``arp``. mDNS finds essentially
    everything (9/9 on the test LAN); http-sweep and arp add MAC addresses
    via the AXIS Digest realm and the ARP cache respectively, which mDNS
    sometimes omits.

    Modes:
      - ``mdns_only=True``: mDNS only (~6s, finds every device that's
        announcing on the LAN). Skip the slower http-sweep/arp methods —
        use this when you trust multicast to work and don't need MAC
        harvesting in this run.
      - ``include_legacy=True``: also run SSDP + WS-Discovery. Useful only
        for fleets containing pre-AXIS-OS-12 devices; both contributed 0
        on the 2026-05-21 test LAN.

    For per-method visibility (e.g. while tuning), use :func:`discover_breakdown`.
    """
    if mdns_only:
        methods = ["mdns"]
    else:
        methods = list(DEFAULT_METHODS)
        if include_legacy:
            methods += list(LEGACY_METHODS)
    bd = discover_breakdown(
        methods=methods,
        mdns_timeout=mdns_timeout,
        arp_probe_http=probe_http_on_arp,
    )
    return bd.merged
