package gateway

import (
	"encoding/json"
	"testing"
)

func TestPortMappingsUnmarshal(t *testing.T) {
	var mappings PortMappings
	err := json.Unmarshal([]byte(`{
        "count": 2,
        "lanIp": "192.0.2.1",
        "mask": "255.255.255.0",
        "pmRule1": {"client":"192.0.2.10","desp":"ssh","enable":1,"exPort":2222,"inPort":22,"protocol":"TCP"},
        "pmRule2": {"client":"192.0.2.20","desp":"game","enable":0,"exPort":8211,"inPort":8211,"protocol":"UDP"}
    }`), &mappings)
	if err != nil {
		t.Fatal(err)
	}
	if len(mappings.Rules) != 2 || mappings.Rules[1].Name != "game" || mappings.Rules[1].IsEnabled() {
		t.Fatalf("unexpected mappings: %#v", mappings)
	}
}

func TestAllInfoUnmarshal(t *testing.T) {
	var info AllInfo
	err := json.Unmarshal([]byte(`{
        "wcount": 1,
        "wlcount": 1,
        "pc1": {"ip":"192.0.2.10","devName":"wired"},
        "wifi1": {"ip":"192.0.2.11","devName":"wireless"}
    }`), &info)
	if err != nil {
		t.Fatal(err)
	}
	if len(info.WiredDevices) != 1 || len(info.WirelessDevices) != 1 {
		t.Fatalf("unexpected device lists: %#v", info)
	}
}

func TestParseProtocol(t *testing.T) {
	protocol, err := ParseProtocol("udp")
	if err != nil || protocol != ProtocolUDP {
		t.Fatalf("ParseProtocol(udp) = %q, %v", protocol, err)
	}
	if _, err := ParseProtocol("icmp"); err == nil {
		t.Fatal("expected unsupported protocol error")
	}
}
