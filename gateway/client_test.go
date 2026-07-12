package gateway

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

var testToken = strings.Repeat("0", 32)

func TestClientLoginReadAndWrite(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/cgi-bin/luci", func(writer http.ResponseWriter, request *http.Request) {
		switch request.Method {
		case http.MethodPost:
			if err := request.ParseForm(); err != nil {
				t.Fatal(err)
			}
			if request.Form.Get("username") != "example-user" || request.Form.Get("psd") != "example-pass" {
				t.Fatal("unexpected login form")
			}
			http.SetCookie(writer, &http.Cookie{Name: "sysauth", Value: "example-session"})
			writer.WriteHeader(http.StatusFound)
		case http.MethodGet:
			fmt.Fprintf(writer, `<script>var token = %q;</script>`, testToken)
		default:
			writer.WriteHeader(http.StatusMethodNotAllowed)
		}
	})
	mux.HandleFunc("/cgi-bin/luci/admin/settings/gwstatus", func(writer http.ResponseWriter, request *http.Request) {
		requireSession(t, request)
		fmt.Fprint(writer, `{"cpuUsed":12,"sysTime":34,"wcount":1,"wlcount":2}`)
	})
	mux.HandleFunc("/cgi-bin/luci/admin/settings/pmSetSingle", func(writer http.ResponseWriter, request *http.Request) {
		requireSession(t, request)
		if err := request.ParseForm(); err != nil {
			t.Fatal(err)
		}
		if request.Form.Get("token") != testToken || request.Form.Get("op") != "disable" || request.Form.Get("srvname") != "example" {
			t.Fatalf("unexpected mutation form: %v", request.Form)
		}
		fmt.Fprint(writer, `{}`)
	})

	server := httptest.NewServer(mux)
	defer server.Close()
	client, err := NewClient(server.URL, "example-user", "example-pass", WithHTTPClient(server.Client()))
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err := client.Login(ctx); err != nil {
		t.Fatal(err)
	}
	status, err := client.Status(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if status.CPUUsed != 12 || status.WirelessDevices != 2 {
		t.Fatalf("unexpected status: %#v", status)
	}
	if err := client.DisablePortMapping(ctx, "example"); err != nil {
		t.Fatal(err)
	}
}

func TestClientRejectsInvalidURL(t *testing.T) {
	if _, err := NewClient("file:///tmp/gateway", "", ""); err == nil {
		t.Fatal("expected invalid scheme error")
	}
}

func requireSession(t *testing.T, request *http.Request) {
	t.Helper()
	cookie, err := request.Cookie("sysauth")
	if err != nil || cookie.Value != "example-session" {
		t.Fatalf("missing session cookie: %v", err)
	}
}
