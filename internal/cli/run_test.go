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
	"github.com/zedoCN/telecom-gateway/internal/credentials"
)

type fakeCredentialStore struct {
	profile  credentials.Profile
	password string
	saved    bool
}

func (store *fakeCredentialStore) Load() (credentials.Profile, error) {
	if !store.saved {
		return credentials.Profile{}, credentials.ErrNoProfile
	}
	return store.profile, nil
}

func (store *fakeCredentialStore) Save(profile credentials.Profile, password string) error {
	store.profile = profile
	store.password = password
	store.saved = true
	return nil
}

func (store *fakeCredentialStore) Password(credentials.Profile) (string, error) {
	if !store.saved {
		return "", credentials.ErrNoProfile
	}
	return store.password, nil
}

func (store *fakeCredentialStore) Delete() error {
	store.saved = false
	store.password = ""
	return nil
}

func (store *fakeCredentialStore) Path() string {
	return "/example/profile.json"
}

func runForTest(args []string, stdin *strings.Reader, stdout, stderr *bytes.Buffer, version string) int {
	return run(args, stdin, stdout, stderr, version, nil, nil)
}

func TestHelpDoesNotRequireCredentials(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if code := runForTest([]string{"help"}, strings.NewReader(""), &stdout, &stderr, "test"); code != 0 {
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
	if code := runForTest([]string{"version"}, strings.NewReader(""), &stdout, &stderr, "v1.2.3"); code != 0 {
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
	if code := runForTest([]string{"status"}, strings.NewReader(""), &stdout, &stderr, "test"); code != 2 {
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
	code := runForTest([]string{"--url", server.URL, "port", "disable", "--name", "example", "--yes"}, strings.NewReader(""), &stdout, &stderr, "test")
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

func TestAuthLoginVerifiesAndStoresCredentials(t *testing.T) {
	t.Setenv("CTGW_USERNAME", "")
	t.Setenv("CTGW_PASSWORD", "")
	token := strings.Repeat("0", 32)
	mux := http.NewServeMux()
	mux.HandleFunc("/cgi-bin/luci", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method == http.MethodPost {
			http.SetCookie(writer, &http.Cookie{Name: "sysauth", Value: "example-session"})
			writer.WriteHeader(http.StatusFound)
			return
		}
		fmt.Fprintf(writer, `<script>var token = %q;</script>`, token)
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	store := &fakeCredentialStore{}
	var stdout, stderr bytes.Buffer
	code := run(
		[]string{"--url", server.URL, "--username", "example-user", "--password-stdin", "auth", "login"},
		strings.NewReader("example-pass\n"),
		&stdout,
		&stderr,
		"test",
		store,
		nil,
	)
	if code != 0 {
		t.Fatalf("run(auth login) = %d, stderr=%s", code, stderr.String())
	}
	if !store.saved || store.profile.URL != server.URL || store.profile.Username != "example-user" || store.password != "example-pass" {
		t.Fatalf("unexpected stored credentials: %#v", store)
	}
	if !strings.Contains(stdout.String(), "verified and stored") {
		t.Fatalf("unexpected stdout: %s", stdout.String())
	}
}

func TestStoredCredentialsAreUsedForReadOnlyCommand(t *testing.T) {
	t.Setenv("CTGW_USERNAME", "")
	t.Setenv("CTGW_PASSWORD", "")
	token := strings.Repeat("0", 32)
	mux := http.NewServeMux()
	mux.HandleFunc("/cgi-bin/luci", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method == http.MethodPost {
			http.SetCookie(writer, &http.Cookie{Name: "sysauth", Value: "example-session"})
			writer.WriteHeader(http.StatusFound)
			return
		}
		fmt.Fprintf(writer, `<script>var token = %q;</script>`, token)
	})
	mux.HandleFunc("/cgi-bin/luci/admin/settings/gwstatus", func(writer http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(writer, `{"cpuUsed":7,"sysTime":60}`)
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	store := &fakeCredentialStore{
		profile:  credentials.Profile{URL: server.URL, Username: "example-user"},
		password: "example-pass",
		saved:    true,
	}
	var stdout, stderr bytes.Buffer
	code := run([]string{"status"}, strings.NewReader(""), &stdout, &stderr, "test", store, nil)
	if code != 0 {
		t.Fatalf("run(status) = %d, stderr=%s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), "7%") {
		t.Fatalf("unexpected stdout: %s", stdout.String())
	}
}
