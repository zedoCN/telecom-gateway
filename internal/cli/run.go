package cli

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"strings"
	"text/tabwriter"
	"time"

	"github.com/zedoCN/telecom-gateway/gateway"
)

type globalOptions struct {
	url           string
	username      string
	passwordStdin bool
	json          bool
	timeout       time.Duration
}

func Run(args []string, stdin io.Reader, stdout, stderr io.Writer, version string) int {
	options, rest, err := parseGlobal(args, stderr)
	if err != nil {
		return 2
	}
	if len(rest) == 0 || rest[0] == "help" || rest[0] == "--help" || rest[0] == "-h" {
		printHelp(stdout)
		return 0
	}
	if rest[0] == "version" {
		fmt.Fprintln(stdout, version)
		return 0
	}

	password := os.Getenv("CTGW_PASSWORD")
	if options.passwordStdin {
		password, err = readPassword(stdin)
		if err != nil {
			fmt.Fprintf(stderr, "ctgw: read password: %v\n", err)
			return 1
		}
	}
	if options.username == "" || password == "" {
		fmt.Fprintln(stderr, "ctgw: credentials required; set CTGW_USERNAME and CTGW_PASSWORD, or use --password-stdin")
		return 2
	}

	ctx, cancel := context.WithTimeout(context.Background(), options.timeout)
	defer cancel()
	client, err := gateway.NewClient(options.url, options.username, password)
	if err != nil {
		fmt.Fprintf(stderr, "ctgw: %v\n", err)
		return 2
	}
	if err := client.Login(ctx); err != nil {
		fmt.Fprintf(stderr, "ctgw: %v\n", err)
		return 1
	}
	if err := execute(ctx, client, rest, options.json, stdout, stderr); err != nil {
		fmt.Fprintf(stderr, "ctgw: %v\n", err)
		return 1
	}
	return 0
}

func parseGlobal(args []string, stderr io.Writer) (globalOptions, []string, error) {
	options := globalOptions{
		url:      envOrDefault("CTGW_URL", "http://192.168.1.1"),
		username: os.Getenv("CTGW_USERNAME"),
		timeout:  15 * time.Second,
	}
	flags := flag.NewFlagSet("ctgw", flag.ContinueOnError)
	flags.SetOutput(stderr)
	flags.StringVar(&options.url, "url", options.url, "gateway base URL")
	flags.StringVar(&options.username, "username", options.username, "gateway username")
	flags.BoolVar(&options.passwordStdin, "password-stdin", false, "read the password from stdin")
	flags.BoolVar(&options.json, "json", false, "write machine-readable JSON")
	flags.DurationVar(&options.timeout, "timeout", options.timeout, "total command timeout")
	if err := flags.Parse(args); err != nil {
		return options, nil, err
	}
	if options.timeout <= 0 {
		return options, nil, errors.New("timeout must be positive")
	}
	return options, flags.Args(), nil
}

func execute(ctx context.Context, client *gateway.Client, args []string, jsonOutput bool, stdout, stderr io.Writer) error {
	switch args[0] {
	case "status":
		status, err := client.Status(ctx)
		if err != nil {
			return err
		}
		if jsonOutput {
			return writeJSON(stdout, status)
		}
		writeStatus(stdout, status)
		return nil
	case "info":
		return runInfo(ctx, client, args[1:], jsonOutput, stdout, stderr)
	case "devices":
		info, err := client.AllInfo(ctx)
		if err != nil {
			return err
		}
		if jsonOutput {
			return writeJSON(stdout, info)
		}
		writeDevices(stdout, info)
		return nil
	case "port":
		return runPort(ctx, client, args[1:], jsonOutput, stdout, stderr)
	case "reboot":
		flags := flag.NewFlagSet("reboot", flag.ContinueOnError)
		flags.SetOutput(stderr)
		yes := flags.Bool("yes", false, "confirm reboot")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if !*yes {
			return errors.New("reboot requires --yes")
		}
		if err := client.Reboot(ctx); err != nil {
			return err
		}
		fmt.Fprintln(stdout, "reboot requested")
		return nil
	default:
		return fmt.Errorf("unknown command %q; run ctgw help", args[0])
	}
}

func runInfo(ctx context.Context, client *gateway.Client, args []string, jsonOutput bool, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("info", flag.ContinueOnError)
	flags.SetOutput(stderr)
	showSensitive := flags.Bool("show-sensitive", false, "include identifiers, SSIDs, and WAN account")
	if err := flags.Parse(args); err != nil {
		return err
	}
	info, err := client.Info(ctx)
	if err != nil {
		return err
	}
	if !*showSensitive {
		info.MAC = ""
		info.SerialNumber = ""
		info.SSID2G = ""
		info.SSID5G = ""
		info.WANAccount = ""
	}
	if jsonOutput {
		return writeJSON(stdout, info)
	}
	writeInfo(stdout, info, *showSensitive)
	return nil
}

func runPort(ctx context.Context, client *gateway.Client, args []string, jsonOutput bool, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("port subcommand required: list, add, enable, disable, or delete")
	}
	switch args[0] {
	case "list":
		mappings, err := client.PortMappings(ctx)
		if err != nil {
			return err
		}
		if jsonOutput {
			return writeJSON(stdout, mappings)
		}
		writePortMappings(stdout, mappings)
		return nil
	case "add":
		flags := flag.NewFlagSet("port add", flag.ContinueOnError)
		flags.SetOutput(stderr)
		name := flags.String("name", "", "mapping name")
		clientIP := flags.String("client", "", "internal client IP")
		protocol := flags.String("protocol", "", "TCP, UDP, or BOTH")
		externalPort := flags.Int("external-port", 0, "external port")
		internalPort := flags.Int("internal-port", 0, "internal port")
		yes := flags.Bool("yes", false, "confirm the change")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if !*yes {
			return errors.New("port add requires --yes")
		}
		if net.ParseIP(*clientIP) == nil {
			return errors.New("--client must be a valid IP address")
		}
		mapping := gateway.PortMapping{Name: *name, Client: *clientIP, Protocol: *protocol, ExternalPort: *externalPort, InternalPort: *internalPort}
		before, err := client.PortMappings(ctx)
		if err != nil {
			return fmt.Errorf("read port mappings before add: %w", err)
		}
		if _, exists := findPortMapping(before.Rules, mapping.Name); exists {
			return fmt.Errorf("port mapping %q already exists; refusing implicit replacement", mapping.Name)
		}
		if err := client.AddPortMapping(ctx, mapping); err != nil {
			return err
		}
		after, err := client.PortMappings(ctx)
		if err != nil {
			return fmt.Errorf("read port mappings after add: %w", err)
		}
		actual, exists := findPortMapping(after.Rules, mapping.Name)
		if !exists || !samePortMapping(actual, mapping) {
			return fmt.Errorf("gateway accepted add request but read-back did not match %q", mapping.Name)
		}
		fmt.Fprintf(stdout, "port mapping %q added and verified\n", *name)
		return nil
	case "enable", "disable", "delete":
		flags := flag.NewFlagSet("port "+args[0], flag.ContinueOnError)
		flags.SetOutput(stderr)
		name := flags.String("name", "", "exact mapping name")
		yes := flags.Bool("yes", false, "confirm the change")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if !*yes {
			return fmt.Errorf("port %s requires --yes", args[0])
		}
		before, err := client.PortMappings(ctx)
		if err != nil {
			return fmt.Errorf("read port mappings before %s: %w", args[0], err)
		}
		current, exists := findPortMapping(before.Rules, *name)
		if !exists {
			return fmt.Errorf("port mapping %q does not exist", *name)
		}
		if args[0] == "enable" && current.IsEnabled() {
			fmt.Fprintf(stdout, "port mapping %q already enabled\n", *name)
			return nil
		}
		if args[0] == "disable" && !current.IsEnabled() {
			fmt.Fprintf(stdout, "port mapping %q already disabled\n", *name)
			return nil
		}
		switch args[0] {
		case "enable":
			err = client.EnablePortMapping(ctx, *name)
		case "disable":
			err = client.DisablePortMapping(ctx, *name)
		case "delete":
			err = client.DeletePortMapping(ctx, *name)
		}
		if err != nil {
			return err
		}
		after, err := client.PortMappings(ctx)
		if err != nil {
			return fmt.Errorf("read port mappings after %s: %w", args[0], err)
		}
		updated, exists := findPortMapping(after.Rules, *name)
		switch args[0] {
		case "enable":
			if !exists || !updated.IsEnabled() {
				return fmt.Errorf("gateway accepted enable request but read-back did not confirm %q", *name)
			}
		case "disable":
			if !exists || updated.IsEnabled() {
				return fmt.Errorf("gateway accepted disable request but read-back did not confirm %q", *name)
			}
		case "delete":
			if exists {
				return fmt.Errorf("gateway accepted delete request but %q still exists", *name)
			}
		}
		fmt.Fprintf(stdout, "port mapping %q %sd and verified\n", *name, args[0])
		return nil
	default:
		return fmt.Errorf("unknown port subcommand %q", args[0])
	}
}

func findPortMapping(mappings []gateway.PortMapping, name string) (gateway.PortMapping, bool) {
	for _, mapping := range mappings {
		if mapping.Name == name {
			return mapping, true
		}
	}
	return gateway.PortMapping{}, false
}

func samePortMapping(actual, expected gateway.PortMapping) bool {
	return actual.Name == expected.Name &&
		actual.Client == expected.Client &&
		strings.EqualFold(actual.Protocol, expected.Protocol) &&
		actual.ExternalPort == expected.ExternalPort &&
		actual.InternalPort == expected.InternalPort
}

func writeStatus(writer io.Writer, status gateway.Status) {
	table := tabwriter.NewWriter(writer, 0, 4, 2, ' ', 0)
	fmt.Fprintf(table, "CPU\t%d%%\n", status.CPUUsed)
	fmt.Fprintf(table, "System uptime\t%s\n", formatDuration(status.SystemUptime))
	fmt.Fprintf(table, "Internet uptime\t%s\n", formatDuration(status.InternetUptime))
	fmt.Fprintf(table, "Wired devices\t%d\n", status.WiredDevices)
	fmt.Fprintf(table, "Wireless devices\t%d\n", status.WirelessDevices)
	fmt.Fprintf(table, "VoIP\t%t\n", status.VoIP)
	fmt.Fprintf(table, "iTV\t%t\n", status.ITV)
	table.Flush()
}

func writeInfo(writer io.Writer, info gateway.Info, showSensitive bool) {
	table := tabwriter.NewWriter(writer, 0, 4, 2, ' ', 0)
	fmt.Fprintf(table, "Device\t%s\n", info.DeviceType)
	fmt.Fprintf(table, "Product\t%s\n", info.ProductClass)
	fmt.Fprintf(table, "Vendor\t%s\n", info.Vendor)
	fmt.Fprintf(table, "Software\t%s\n", info.Software)
	fmt.Fprintf(table, "LAN IPv4\t%s\n", info.LANIP)
	fmt.Fprintf(table, "LAN IPv6\t%s\n", info.LANIPv6)
	fmt.Fprintf(table, "WAN IPv4\t%s\n", info.WANIP)
	fmt.Fprintf(table, "WAN IPv6\t%s\n", info.WANIPv6)
	fmt.Fprintf(table, "Wi-Fi enabled\t%t\n", info.WiFiEnabled)
	if showSensitive {
		fmt.Fprintf(table, "MAC\t%s\n", info.MAC)
		fmt.Fprintf(table, "Serial\t%s\n", info.SerialNumber)
		fmt.Fprintf(table, "SSID 2.4 GHz\t%s\n", info.SSID2G)
		fmt.Fprintf(table, "SSID 5 GHz\t%s\n", info.SSID5G)
		fmt.Fprintf(table, "WAN account\t%s\n", info.WANAccount)
	}
	table.Flush()
}

func writeDevices(writer io.Writer, info gateway.AllInfo) {
	table := tabwriter.NewWriter(writer, 0, 4, 2, ' ', 0)
	fmt.Fprintln(table, "LINK\tNAME\tIP\tTYPE\tBRAND\tMODEL\tONLINE")
	for _, device := range info.WiredDevices {
		writeDevice(table, "wired", device)
	}
	for _, device := range info.WirelessDevices {
		writeDevice(table, "wireless", device)
	}
	table.Flush()
}

func writeDevice(writer io.Writer, link string, device gateway.Device) {
	fmt.Fprintf(writer, "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", link, device.Name, device.IP, device.Type, device.Brand, device.Model, formatDuration(device.OnlineSeconds))
}

func writePortMappings(writer io.Writer, mappings gateway.PortMappings) {
	table := tabwriter.NewWriter(writer, 0, 4, 2, ' ', 0)
	fmt.Fprintln(table, "NAME\tENABLED\tCLIENT\tPROTOCOL\tEXTERNAL\tINTERNAL")
	for _, mapping := range mappings.Rules {
		fmt.Fprintf(table, "%s\t%t\t%s\t%s\t%d\t%d\n", mapping.Name, mapping.IsEnabled(), mapping.Client, mapping.Protocol, mapping.ExternalPort, mapping.InternalPort)
	}
	table.Flush()
}

func writeJSON(writer io.Writer, value any) error {
	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}

func readPassword(reader io.Reader) (string, error) {
	password, err := bufio.NewReader(reader).ReadString('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return "", err
	}
	password = strings.TrimRight(password, "\r\n")
	if password == "" {
		return "", errors.New("empty password")
	}
	return password, nil
}

func formatDuration(seconds int64) string {
	if seconds < 0 {
		return strconv.FormatInt(seconds, 10)
	}
	return (time.Duration(seconds) * time.Second).String()
}

func envOrDefault(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func printHelp(writer io.Writer) {
	fmt.Fprint(writer, `ctgw manages supported China Telecom residential gateways.

Usage:
  ctgw [global flags] <command> [command flags]

Commands:
  status                         Show gateway status
  info [--show-sensitive]        Show gateway information
  devices                        List connected devices
  port list                      List port mappings
  port add [flags]               Add one port mapping
  port enable --name NAME --yes  Enable one exact mapping
  port disable --name NAME --yes Disable one exact mapping
  port delete --name NAME --yes  Delete one exact mapping
  reboot --yes                   Reboot the gateway
  version                        Print the ctgw version

Global flags:
  --url URL           Gateway URL (default CTGW_URL or http://192.168.1.1)
  --username NAME     Gateway username (default CTGW_USERNAME)
  --password-stdin    Read the password from stdin instead of CTGW_PASSWORD
  --json              Write JSON output
  --timeout DURATION  Total command timeout (default 15s)

Run read-only commands before any change. Mutating commands always require --yes.
`)
}
