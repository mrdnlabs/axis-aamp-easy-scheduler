# Axis device onboarding — empirical reference

What we learned while building and testing the discovery + onboarding pipeline against real hardware. Most of this is **not in Axis's public documentation**, or contradicts what's documented; the source-of-truth column says which we verified directly.

**Reference device for verification: C1110-E Network Cabinet Speaker, AXIS OS 12.9.57, aarch64.** Some findings may differ on other models or firmware — call them out as they're discovered.

---

## 1. Discovery protocols

### What Axis devices actually expose

| Protocol | Layer | Address / port | Default-on in AXIS OS 12+ | Source |
|---|---|---|---|---|
| **Bonjour / mDNS** | UDP | 5353, `224.0.0.251` | ✅ Yes | Axis hardening guide + verified |
| **SSDP** | UDP | 1900, `239.255.255.250` | ❌ No (off in 12.0+) | Axis hardening guide |
| **UPnP** | TCP | 49152 | ❌ No (off in 12.0+) | Axis hardening guide |
| **WS-Discovery** | UDP | 3702, `239.255.255.250` | ❌ No (off in 12.1+) | Axis hardening guide |
| **LLDP** | L2 | EtherType 0x88CC | ✅ Yes (factory default) | Axis hardening guide |
| **CDP** | L2 | link-local | ✅ Yes (factory default) | Axis hardening guide |

The hardening guide explicitly says: *"Axis devices adhere to IT industry standard discovery protocols such as Link Layer Discovery Protocol (LLDP), Cisco Discovery Protocol (CDP) and Bonjour/MDNS to share device information in factory default state."*

### What we run, what's actually productive

Empirical run on a 9-device fleet (test LAN, 2026-05-21):

| Method | Hits | Notes |
|---|---|---|
| mDNS (multi-service browse) | 9 / 9 | Workhorse |
| HTTP subnet sweep | 5 / 9 | Harvests MAC from `AXIS_<MAC>` Digest realm |
| ARP-cache filter | 7 / 9 | All 3 modern Axis OUIs present in real fleet |
| SSDP | **0 / 9** | Off-by-default on OS 12.0+ |
| WS-Discovery | **0 / 9** | Off-by-default on OS 12.1+ |

`discover_all()` runs mDNS + http-sweep + arp in parallel by default. SSDP and WS-Discovery are gated behind `include_legacy=True` for fleets that still include pre-OS-12 devices.

### mDNS service types

| Service type | Used by | Verified |
|---|---|---|
| `_axis-video._tcp.local.` | All Axis devices on the test LAN (cameras + audio) | ✅ all 9 devices |
| `_axis-audiosite._tcp.local.` | Audio-specific (only seen on C1110-E + a few others) | ✅ 1 device |
| `_axis-nvr._tcp.local.` | NVRs only | Axis dev docs |
| `_axis-bws._tcp.local.` | Older Bonjour Web Service | Not seen on test LAN |
| `_http._tcp.local.` | All Axis devices (generic) | Seen but redundant with `_axis-video` — dropped from seed list |

**`discover_mdns()` also browses the meta-service** `_services._dns-sd._udp.local.` and auto-adds any `_axis-*` types it discovers, so we don't have to guess service names that aren't publicly documented. That's how we found `_axis-audiosite._tcp.local.`.

### Axis IEEE OUI assignments

The IEEE OUI registry (oui.txt, 236k+ lines) lists **exactly four** OUIs registered to "Axis Communications AB":

| OUI | Registered |
|---|---|
| `00:40:8C` | 1998-04-22 |
| `AC:CC:8E` | 2011-08-05 |
| `B8:A4:4F` | 2019-03-07 |
| `E8:27:25` | 2023-12-08 |

No MA-M (28-bit) or MA-S (36-bit) blocks. Devices with non-Axis OUIs are OEM/whitelabel hardware (2N etc., which Axis owns) or use chipset-vendor MACs — these get caught by the HTTP sweep, not the OUI filter.

---

## 2. VAPIX CGI conventions (the most surprising part)

**Axis doesn't use HTTP methods consistently.** Different CGIs require different methods, and getting it wrong returns misleading errors. Verified against C1110-E fw 12.9:

| Endpoint | Method | What happens if you use the other |
|---|---|---|
| `/axis-cgi/basicdeviceinfo.cgi` | POST (JSON-RPC) | GET → 2002 "HTTP request type 'GET' not supported" |
| `/axis-cgi/systemready.cgi` | POST (JSON-RPC) | (unverified) |
| `/axis-cgi/apidiscovery.cgi` | POST (JSON-RPC) | GET → 2002 error |
| `/axis-cgi/param.cgi?action=list` | **GET** | POST → may "work" but unreliable |
| `/axis-cgi/param.cgi?action=update` | **GET** | POST → `'action must be specified'` |
| `/axis-cgi/pwdgrp.cgi?action=add` | **GET** | POST → 401 Unauthorized (params not parsed) |
| `/axis-cgi/pwdgrp.cgi?action=update` | **GET** | POST → same as above |
| `/axis-cgi/applications/list.cgi` | GET | (unverified) |
| `/axis-cgi/applications/upload.cgi` | POST (multipart) | — |
| `/axis-cgi/applications/control.cgi` | POST or GET | Either works |
| `/axis-cgi/hardfactorydefault.cgi` | GET | — |
| `/axis-cgi/restart.cgi` | POST or GET | — |

**Rule of thumb**: legacy CGIs (param, pwdgrp, factorydefault, applications/list, applications/control) use GET. JSON-RPC CGIs (basicdeviceinfo, systemready, apidiscovery) use POST. Multipart uploads use POST.

The POST-vs-GET mismatch is the cause of two of the most baffling errors:
- `param_set` returning `'action must be specified'` — the URL query string isn't parsed on POST.
- `create_root` returning 401 even when no user exists yet — same reason.

### Authentication

| Endpoint | Auth required? |
|---|---|
| `/axis-cgi/basicdeviceinfo.cgi` | **Yes, on AXIS OS 12+** — returns `WWW-Authenticate: Digest realm="AXIS_<MAC>"`. Was unauthenticated on older firmware. |
| `/axis-cgi/systemready.cgi` | No (responds with the JSON envelope unauthenticated) |
| `/axis-cgi/pwdgrp.cgi?action=add` | No (factory-fresh device, no users yet) |
| `/axis-cgi/pwdgrp.cgi?action=update` | Yes (Digest as current user) |
| `/axis-cgi/param.cgi` | Yes (both list and update) |
| `/axis-cgi/applications/*.cgi` | Yes |
| `/axis-cgi/hardfactorydefault.cgi` | Yes |

**The `AXIS_<MAC>` Digest realm is gold for discovery.** Even on a device with auth required, a 401 from `/axis-cgi/basicdeviceinfo.cgi` includes `realm="AXIS_<12-hex-MAC>"`. That's:
- Positive Axis identification (any other web server would return a different realm)
- The device's MAC for free, without authenticating

The HTTP subnet sweep relies on this. Regex used: `realm="AXIS_([0-9A-Fa-f]{12})"`.

---

## 3. Initial setup and authentication

### `needs_initial_setup` is the source of truth

Use `/axis-cgi/systemready.cgi`'s `needsetup` field — **not 401 inference** — to decide whether a device needs initial setup:

```python
needs = str(data.get("needsetup", "")).lower()
return needs in ("yes", "true", "1")
```

A 401 from `basicdeviceinfo.cgi` means "wrong password", not "no user exists". Per AXIS OS 11.6+:
- Pre-11.6: `root` pre-exists with no password; first `pwdgrp.cgi?action=add` sets one.
- 11.6+: no user exists at all; same endpoint creates root.

### `passphrasepolicy: none` is the default

On a factory-fresh AXIS OS 12.9 device, `systemready.cgi` reports `passphrasepolicy: none`. The 4-character password `pass` was accepted by `pwdgrp.cgi?action=add`. **There is no enforced complexity policy at first-touch.** This may differ on customer-configured devices that have a stricter policy installed.

Don't rely on this — production code should still use strong passwords. But it means the onboarding code path doesn't have to handle complexity-rejection errors specially.

### Reboot timing

| Operation | Time until unreachable | Time until back online |
|---|---|---|
| `restart.cgi` (soft) | ~5–10s | 30–60s |
| `hardfactorydefault.cgi` | ~7s | **~30s** (much faster than the 60–90s I'd budgeted) |

So `wait_until_reachable` can poll more aggressively. The 30s ballpark holds across the C1110-E fleet but may differ for other models.

---

## 4. ACAP install — model/arch and error codes

### Architecture: ignore the heuristic table, prefer the device's self-report

`MODEL_ARCH_TABLE` in `acap.py` is a fallback heuristic for pre-auth scenarios. It has been wrong:

- **C1110-E**: I originally tagged it `armv7hf` based on product line; the device's `basicdeviceinfo.cgi` reports `aarch64`. (Verified 2026-05-21.)
- Implication: any other audio device whose generation isn't verified may also be wrong.

**Always prefer `basic_info.architecture` from the device itself when available.** `onboard.py` now does this — it auto-elevates `basic_info` to authenticated after a successful login, then uses the device-reported arch as `arch_override` to `resolve_eap()`.

### Axis upload error codes

`/axis-cgi/applications/upload.cgi` returns 200 with body `"Error: N"` on failure. Decoded:

| Code | Meaning |
|---|---|
| 1 | Invalid .eap package format |
| 4 | Already installed (some firmware) |
| **5** | **Wrong CPU architecture for this device** ← the misleading one |
| 6 | Out of space / no flash |

We surface these with hints in `VapixError.body`.

### "A" vs "B" variant ACAP

The AAM Pro installer drops two .eap variants per architecture:

```
AXIS_Audio_Manager_Pro_5_1_34_<arch>.eap        # A: appName=AudioManagerPro,  appId=414689
AXIS_Audio_Manager_Pro_B_5_1_34_<arch>.eap      # B: appName=AudioManagerProB, appId=414773
```

Per the `package.conf` / `manifest.json` inside each `.eap`, A and B are **identical except for `appName` and `appId`**. Same architecture, same `paramConfig` (both expect `PrimaryServerIpAddress` + `PrimaryServerTlsPort=6998`), same dbus methods, same fw_install script. Different `appId` is exactly the mechanism Axis OS uses to allow **two ACAPs to coexist on one device**.

**Axis does NOT publicly document the A/B distinction.** Public docs (help.axis.com, the AAM Pro user manual, support FAQ) say nothing. The only authoritative source is the manifests inside each `.eap`.

Our current default: install the A variant ("AudioManagerPro") on every device. `acap.PAGING_MODELS` is empty until we verify a model that actually needs B (or needs both A and B). Don't speculate — confirm against hardware first.

### `.img` files

The AAM Pro installer also drops files like `AudioManagerPro_aarch64.img`. These are **not** an alternate install package. Reading the `fw_install.sh` bundled inside every `.eap`:

```
head $AAMP_ROOT/localdata/AudioManagerPro.img -c64 > fwversion.txt
tail -c+65 $AAMP_ROOT/localdata/AudioManagerPro.img > AudioManagerPro.tgz
```

First 64 bytes are an ASCII `fwversion.txt` header (`"AudioManagerPro-<version>"`); the rest is the same `AudioManagerPro.tgz` payload that's inside the `.eap`. The `.img` is an **in-place upgrade artifact** that the AAM Pro server pushes to an already-installed ACAP via its own server-to-device protocol over TLS port 6998. Not relevant to first-time onboarding — use the `.eap`.

The `armv7hf_LT_11_8.img` variant ("LT" = "less than") is for armv7hf devices on AXIS OS < 11.8, which have a different ABI/lib expectations.

### Package name in `applications/list.cgi`

The Axis `Name` attribute returned by `/axis-cgi/applications/list.cgi` for the AAM Pro ACAP is **`AudioManagerPro`** (CamelCase, no underscore). NOT `aampro`. The `friendlyName`/`NiceName` is `"AXIS Audio Manager Pro"`. We had this wrong initially.

---

## 5. AAM Pro server pointer (`param.cgi`)

### The actual parameter key

Per the .eap manifest, the leaf parameter name is `PrimaryServerIpAddress`. Per `param.cgi?action=list&group=AudioManagerPro` output on real firmware, the full path is:

```
root.AudioManagerPro.PrimaryServerIpAddress
```

Note the `root.` prefix. The leaf name matches the manifest, but the path includes the top-level group prefix when listed. `param_set()` uses this full key verbatim. Some older firmware may strip the `root.` prefix — `SERVER_POINTER_CANDIDATES` in `onboard.py` includes both forms.

Full set of params on a fresh C1110-E after the ACAP starts:

```
root.AudioManagerPro.Diagnostics = '0'
root.AudioManagerPro.PrimaryServerIpAddress = ''
root.AudioManagerPro.PrimaryServerTcpPort = '0'
root.AudioManagerPro.PrimaryServerTlsPort = '6998'
root.AudioManagerPro.SecondaryServerIpAddress = ''
root.AudioManagerPro.SecondaryServerTcpPort = '0'
root.AudioManagerPro.SecondaryServerTlsPort = '6998'
```

The `Secondary*` slots strongly suggest a primary/backup deployment mode — likely the role of the "B" variant ACAP, but unverified.

### Which IP to set

This is the part that took the most thinking. The naive answer "use `cfg.host`" is wrong in three common cases:

1. **AAM Pro running on `localhost`** (the operator's own machine). The device can't route to `localhost` on a remote machine.
2. **AAM Pro server has multiple network interfaces** (e.g. one for management/internet, one for the device VLAN). The `socket.connect("8.8.8.8")` trick to find "our IP" returns the management-NIC IP, not the device-facing one.
3. **AAM Pro behind NAT**, devices on the WAN side, need to use a public hostname.

`onboard._server_pointer_value(cfg, device_ip)` resolves in this order:

1. **Explicit override** — `AAMP_DEVICE_FACING_HOST` from `.aamp_credentials` if set. Verbatim, no transforms. Use this for NAT/FQDN deployments.
2. **Per-device interface inference** — when `cfg.host` is localhost/127.0.0.1, open a UDP socket and `connect((device_ip, 1))`. UDP `connect()` doesn't send anything — it just makes the kernel resolve the route to `device_ip` and bind our end to the right interface. `getsockname()` then returns the IP of the interface that routes to that specific device. Correct for multi-homed servers AND works per-device (device A on subnet 192.168.1.0/24 gets `192.168.1.50`; device B on 10.0.5.0/24 gets `10.0.5.50` — both told by the same AAM Pro server).
3. **Fallback** — strip scheme/port from `cfg.host` and use the hostname.

---

## 6. Factory reset specifics

### Endpoint variants

| Endpoint | Wipes |
|---|---|
| `/axis-cgi/hardfactorydefault.cgi` | Everything: settings, credentials, ACAPs, **and network config** |
| `/axis-cgi/factorydefault.cgi` | Settings, credentials, ACAPs, but **keeps** IP / DNS / hostname |
| `/axis-cgi/restore.cgi` | Settings only — softer reset |

We default to `hardfactorydefault.cgi` for clean fleet wipes, but `factory_default(hard=False)` is available when you don't want to risk losing the device to DHCP weirdness.

### Response shape

The endpoint returns an HTML meta-refresh page:

```html
<html><head><meta http-equiv="refresh" content="0;URL=/admin/factoryMessage2.shtml?server=192.168.1.220"></head><body></body></html>
```

That's success. The device starts rebooting essentially immediately. The TCP connection often closes mid-response — `factory_default()` treats a connection-error after sending the request as success rather than failure.

### Re-discovery after reset

On the C1110-E, DHCP renewed at the same address after `hardfactorydefault.cgi`. In a stricter environment (very short leases, different VLAN assignments), the device might come back at a different IP — fall back to mDNS re-discovery in that case.

---

## 7. Stuff that took longer than it should have

A non-exhaustive list of misleading dead-ends I went through, captured so the next person doesn't repeat them:

- "Axis kept the historical `_axis-video._tcp` name even for audio devices" — I asserted this confidently from a vague memory; turned out to be true for cameras AND audio, but the audio devices ALSO advertise `_axis-audiosite._tcp` which is the more specific service. Always browse the mDNS meta-service to find what's actually registered.
- "B variant is for paging consoles" — pure speculation. The manifests show A and B are identical except for `appName`/`appId`. Don't hardcode model lists until you have hardware.
- "Axis has 10 OUIs" — I hallucinated 6 of them. There are 4. Verify against `https://standards-oui.ieee.org/oui/oui.txt`.
- "POST is fine for all Axis CGIs" — wrong; the GET-only CGIs (param.cgi, pwdgrp.cgi) return misleading errors on POST.
- "`/axis-cgi/basicdeviceinfo.cgi` responds unauthenticated" — was true on older firmware; on AXIS OS 12+ it requires auth and returns empty `propertyList` unauthenticated. Always auto-elevate.
- "`MODEL_ARCH_TABLE` based on product-line generation is reliable" — wrong. Verify against the device's `basicdeviceinfo.cgi` Architecture field, which is authoritative.

---

## 8. Distinguishing audio devices from other Axis products

During discovery we encounter cameras, intercoms, access-control devices, and audio devices all mixed together. To filter for "is this an Axis network audio device?" we use three signals, in decreasing order of strength:

1. **mDNS service type** `_axis-audiosite._tcp.local.` — audio-specific. Only audio firmware advertises here. Strongest pre-auth signal.
2. **Catalog match on the model number** (from `basic_info` after auth). The catalog lives in `src/aamp/axis_models.py` and was assembled from axis.com product pages 2026-05-21. Includes both current and recently-discontinued models.
3. **Prefix heuristic** for models not yet in the catalog: `C1xxx`, `C2xxx`, `C3xxx`, `D3xxx`, `D4xxx`, `XC1xxx` → speakers; `C6xxx` → paging consoles; `C8xxx` → amplifiers/bridges/volume controllers; `D6xxx` → audio-capable sensors. Trailing `?` on the subtype label (`"speaker?"`) indicates a heuristic match — verify against hardware before adding to the catalog.

C7xxx is **NOT** an audio endpoint — those are AAM Pro server appliances (C7050, C7050 Mk II/III, C7110) running AAM Pro itself. The catalog tags them as `aam-pro-server` so the onboarding flow can skip them.

Model naming families verified across all Axis products:
| Prefix | Family |
|---|---|
| `C1xxx-C3xxx` | Network speakers |
| `C6xxx` | Network paging consoles |
| `C7xxx` | AAM Pro server appliances (Windows IoT hardware) |
| `C8xxx` | Network audio system devices (amp, bridge, volume controller) |
| `D3xxx`, `D4xxx` | Audio-emitting accessories (legacy/strobe) |
| `D6xxx` | Sensors with speakers |
| `M-`, `P-`, `Q-`, `F-`-series | Cameras |
| `I-`-series | Intercoms |
| `A-`-series | Access control |
| `T-`-series | Accessories / mounts |

API for callers: `aamp.axis_models.is_audio_device(model)`, `classify_device(model)`, `audio_subtype(model)`. `DiscoveredDevice` carries `device_class` and `audio_subtype` fields, populated automatically during discovery.

## 9. Open questions for future verification

These remain unverified at the time of writing. Add to this section as devices are tested:

- Does any model **need** the "B" variant ACAP installed (vs. just the A variant)?
- Does any deployment **need both** A and B installed on the same device?
- What's the actual mDNS service registered by other AXIS OS 11.4+ audio devices besides C1110-E? Is `_axis-audiosite` universal for newer audio firmware?
- Does `param.cgi`'s response key prefix (`root.` or no `root.`) vary by firmware version?
- What's the right way to delete an ACAP via VAPIX? (Not used by current onboarding flow — would be needed for upgrades or fleet decom.)
- What's the AAM Pro server-to-device protocol over TLS 6998? The `.img` in-place upgrade artifact gets pushed through here, but the wire protocol isn't documented.
