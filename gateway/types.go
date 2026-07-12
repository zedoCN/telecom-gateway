package gateway

import (
	"encoding/json"
	"fmt"
	"strings"
)

// Protocol is a port-mapping transport accepted by the gateway.
type Protocol string

const (
	ProtocolTCP  Protocol = "TCP"
	ProtocolUDP  Protocol = "UDP"
	ProtocolBoth Protocol = "BOTH"
)

func ParseProtocol(value string) (Protocol, error) {
	protocol := Protocol(strings.ToUpper(value))
	switch protocol {
	case ProtocolTCP, ProtocolUDP, ProtocolBoth:
		return protocol, nil
	default:
		return "", fmt.Errorf("unsupported protocol %q: use TCP, UDP, or BOTH", value)
	}
}

type Status struct {
	CPUUsed         int   `json:"cpuUsed"`
	ITV             bool  `json:"itv"`
	StorageCount    int   `json:"scount"`
	SystemUptime    int64 `json:"sysTime"`
	InternetUptime  int64 `json:"upTime"`
	VoIP            bool  `json:"voip"`
	WiredDevices    int   `json:"wcount"`
	WirelessDevices int   `json:"wlcount"`
}

type Info struct {
	DeviceType   string `json:"DevType,omitempty"`
	WiFiEnabled  bool   `json:"wifiOnOff"`
	LANIP        string `json:"LANIP,omitempty"`
	LANIPv6      string `json:"LANIPv6,omitempty"`
	MAC          string `json:"MAC,omitempty"`
	ProductClass string `json:"ProductCls,omitempty"`
	SerialNumber string `json:"ProductSN,omitempty"`
	Software     string `json:"SWVer,omitempty"`
	Vendor       string `json:"Vendor,omitempty"`
	WANIP        string `json:"WANIP,omitempty"`
	WANIPv6      string `json:"WANIPv6,omitempty"`
	SSID2G       string `json:"ssid2g,omitempty"`
	SSID5G       string `json:"ssid5g,omitempty"`
	WANAccount   string `json:"wanAcnt,omitempty"`
}

type Device struct {
	UploadSpeed   int64  `json:"upSpeed"`
	IP            string `json:"ip,omitempty"`
	OnlineSeconds int64  `json:"onlineTime"`
	Model         string `json:"model,omitempty"`
	DownloadSpeed int64  `json:"downSpeed"`
	Name          string `json:"devName,omitempty"`
	Type          string `json:"type,omitempty"`
	Brand         string `json:"brand,omitempty"`
}

type AllInfo struct {
	WirelessUpload   int64    `json:"tWlUp"`
	WirelessDownload int64    `json:"tWlDown"`
	WiredUpload      int64    `json:"tWUp"`
	WiredDownload    int64    `json:"tWDown"`
	WANUptime        int64    `json:"wanUpTime"`
	StorageCount     int      `json:"scount"`
	VoIP             bool     `json:"voip"`
	WANConnected     string   `json:"wanConnect,omitempty"`
	WiredCount       int      `json:"wcount"`
	WirelessCount    int      `json:"wlcount"`
	ITV              bool     `json:"itv"`
	WiredDevices     []Device `json:"pc,omitempty"`
	WirelessDevices  []Device `json:"wifi,omitempty"`
}

func (info *AllInfo) UnmarshalJSON(data []byte) error {
	type alias AllInfo
	var base alias
	if err := json.Unmarshal(data, &base); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	*info = AllInfo(base)
	info.WiredDevices = nil
	info.WirelessDevices = nil
	for i := 1; i <= info.WiredCount; i++ {
		if raw, ok := fields[fmt.Sprintf("pc%d", i)]; ok {
			var device Device
			if err := json.Unmarshal(raw, &device); err != nil {
				return fmt.Errorf("decode pc%d: %w", i, err)
			}
			info.WiredDevices = append(info.WiredDevices, device)
		}
	}
	for i := 1; i <= info.WirelessCount; i++ {
		if raw, ok := fields[fmt.Sprintf("wifi%d", i)]; ok {
			var device Device
			if err := json.Unmarshal(raw, &device); err != nil {
				return fmt.Errorf("decode wifi%d: %w", i, err)
			}
			info.WirelessDevices = append(info.WirelessDevices, device)
		}
	}
	return nil
}

type PortMapping struct {
	Client       string `json:"client"`
	Name         string `json:"desp"`
	Enabled      int    `json:"enable"`
	ExternalPort int    `json:"exPort"`
	InternalPort int    `json:"inPort"`
	Protocol     string `json:"protocol"`
}

func (mapping PortMapping) IsEnabled() bool {
	return mapping.Enabled != 0
}

type PortMappings struct {
	Count int           `json:"count"`
	LANIP string        `json:"lanIp,omitempty"`
	Mask  string        `json:"mask,omitempty"`
	Rules []PortMapping `json:"pmRule,omitempty"`
}

func (mappings *PortMappings) UnmarshalJSON(data []byte) error {
	type alias PortMappings
	var base alias
	if err := json.Unmarshal(data, &base); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	*mappings = PortMappings(base)
	mappings.Rules = nil
	for i := 1; i <= mappings.Count; i++ {
		raw, ok := fields[fmt.Sprintf("pmRule%d", i)]
		if !ok {
			continue
		}
		var mapping PortMapping
		if err := json.Unmarshal(raw, &mapping); err != nil {
			return fmt.Errorf("decode pmRule%d: %w", i, err)
		}
		mappings.Rules = append(mappings.Rules, mapping)
	}
	return nil
}
