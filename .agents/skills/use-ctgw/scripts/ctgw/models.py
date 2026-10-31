"""Whitelist and normalize the gateway's model-specific JSON responses."""

MAX_COUNT = 4096


class GatewayError(Exception):
    """A safe-to-display validation, authentication, or protocol error."""


def _object(value):
    if not isinstance(value, dict):
        raise GatewayError("gateway response must be a JSON object")
    return value


def _fields(value, integers=(), booleans=(), strings=(), optional_strings=()):
    _object(value)
    result = {}
    for names, expected, default in (
        (integers, int, 0), (booleans, bool, False),
        (strings, str, ""), (optional_strings, str, ""),
    ):
        for name in names:
            item = value.get(name)
            if item is None:
                item = default
            if type(item) is not expected:
                raise GatewayError("gateway response contains an invalid field type")
            if expected is int and not -(1 << 63) <= item < (1 << 63):
                raise GatewayError("gateway response integer is out of range")
            if names is optional_strings and item == "":
                continue
            result[name] = item
    return result


def _count(value, name):
    count = value[name]
    if not 0 <= count <= MAX_COUNT:
        raise GatewayError("gateway response count is out of range")
    return count


def status(value):
    result = _fields(value,
        integers=("cpuUsed", "scount", "sysTime", "upTime", "wcount", "wlcount"),
        booleans=("itv", "voip"))
    for name in ("scount", "wcount", "wlcount"):
        _count(result, name)
    return result


def info(value):
    return _fields(value, booleans=("wifiOnOff",), optional_strings=(
        "DevType", "LANIP", "LANIPv6", "MAC", "ProductCls", "ProductSN", "SWVer",
        "Vendor", "WANIP", "WANIPv6", "ssid2g", "ssid5g", "wanAcnt"))


def devices(value):
    result = _fields(value,
        integers=("tWlUp", "tWlDown", "tWUp", "tWDown", "wanUpTime", "scount", "wcount", "wlcount"),
        booleans=("voip", "itv"), optional_strings=("wanConnect",))
    _count(result, "scount")
    for prefix, count_name in (("pc", "wcount"), ("wifi", "wlcount")):
        entries = []
        for index in range(1, _count(result, count_name) + 1):
            key = f"{prefix}{index}"
            if key in value:
                entries.append(_fields(value[key],
                    integers=("upSpeed", "onlineTime", "downSpeed"),
                    optional_strings=("ip", "model", "devName", "type", "brand")))
        if entries:
            result[prefix] = entries
    return result


def port_mappings(value):
    result = _fields(value, integers=("count",), optional_strings=("lanIp", "mask"))
    entries = []
    for index in range(1, _count(result, "count") + 1):
        key = f"pmRule{index}"
        if key in value:
            entries.append(_fields(value[key], integers=("enable", "exPort", "inPort"),
                                   strings=("client", "desp", "protocol")))
    if entries:
        result["pmRule"] = entries
    return result
