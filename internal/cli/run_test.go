package cli

import (
	"bytes"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/zedoCN/telecom-gateway/gateway"
)

func TestHelpDoesNotRequireCredentials(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if code := Run([]string{"help"}, strings.NewReader(""), &stdout, &stderr, "test"); code != 0 {
		t.Fatalf("Run(help) = %d, stderr=%s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), "port list") {
		t.Fatalf("unexpected help: %s", stdout.String())
	}
}

func TestFindAndComparePortMapping(t *testing.T) {
	mappings := []gateway.PortMapping{{
		Name:         "example",
		Client:       "192.0.2.10",
		Protocol:     "UDP",
		ExternalPort: 8211,
		InternalPort: 8211,
	}}
	actual, found := findPortMapping(mappings, "example")
	if !found {
		t.Fatal("expected mapping to be found")
	}
	expected := gateway.PortMapping{
		Name:         "example",
		Client:       "192.0.2.10",
		Protocol:     "udp",
		ExternalPort: 8211,
		InternalPort: 8211,
	}
	if !samePortMapping(actual, expected) {
		t.Fatalf("expected mappings to match: %#v %#v", actual, expected)
	}
	if _, found := findPortMapping(mappings, "missing"); found {
		t.Fatal("unexpected mapping match")
	}
}

func TestVersionDoesNotRequireCredentials(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if code := Run([]string{"version"}, strings.NewReader(""), &stdout, &stderr, "v1.2.3"); code != 0 {
		t.Fatalf("Run(version) = %d, stderr=%s", code, stderr.String())
	}
	if stdout.String() != "v1.2.3\n" {
		t.Fatalf("unexpected version: %q", stdout.String())
	}
}

func TestOperationalCommandRequiresCredentials(t *testing.T) {
	t.Setenv("CTGW_USERNAME", "")
	t.Setenv("CTGW_PASSWORD", "")
	var stdout, stderr bytes.Buffer
	if code := Run([]string{"status"}, strings.NewReader(""), &stdout, &stderr, "test"); code != 2 {
		t.Fatalf("Run(status) = %d", code)
	}
	if !strings.Contains(stderr.String(), "credentials required") {
		t.Fatalf("unexpected stderr: %s", stderr.String())
	}
}

func TestPortDisablePerformsReadback(t *testing.T) {
	t.Setenv("CTGW_USERNAME", "example-user")
	t.Setenv("CTGW_PASSWORD", "example-pass")
	token := strings.Repeat("0", 32)
	var mu sync.Mutex
	enabled := true
	reads := 0
	writes := 0

	mux := http.NewServeMux()
	mux.HandleFunc("/cgi-bin/luci", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method == http.MethodPost {
			http.SetCookie(writer, &http.Cookie{Name: "sysauth", Value: "example-session"})
			writer.WriteHeader(http.StatusFound)
			return
		}
		fmt.Fprintf(writer, `<script>var token = %q;</script>`, token)
	})
	mux.HandleFunc("/cgi-bin/luci/admin/settings/pmDisplay", func(writer http.ResponseWriter, _ *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		reads++
		enable := 0
		if enabled {
			enable = 1
		}
		fmt.Fprintf(writer, `{"count":1,"pmRule1":{"client":"192.0.2.10","desp":"example","enable":%d,"exPort":8211,"inPort":8211,"protocol":"UDP"}}`, enable)
	})
	mux.HandleFunc("/cgi-bin/luci/admin/settings/pmSetSingle", func(writer http.ResponseWriter, request *http.Request) {
		if err := request.ParseForm(); err != nil {
			t.Errorf("parse mutation form: %v", err)
			writer.WriteHeader(http.StatusBadRequest)
			return
		}
		if request.Form.Get("token") != token || request.Form.Get("op") != "disable" || request.Form.Get("srvname") != "example" {
			t.Errorf("unexpected mutation form: %v", request.Form)
		}
		mu.Lock()
		enabled = false
		writes++
		mu.Unlock()
		fmt.Fprint(writer, `{}`)
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	var stdout, stderr bytes.Buffer
	code := Run([]string{"--url", server.URL, "port", "disable", "--name", "example", "--yes"}, strings.NewReader(""), &stdout, &stderr, "test")
	if code != 0 {
		t.Fatalf("Run(port disable) = %d, stderr=%s", code, stderr.String())
	}
	mu.Lock()
	defer mu.Unlock()
	if reads != 2 || writes != 1 || enabled {
		t.Fatalf("reads=%d writes=%d enabled=%t", reads, writes, enabled)
	}
	if !strings.Contains(stdout.String(), "disabled and verified") {
		t.Fatalf("unexpected stdout: %s", stdout.String())
	}
}
