package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

const maxResponseBytes = 8 << 20

var tokenPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)token[^a-z0-9]+([a-z0-9]{32})`),
	regexp.MustCompile(`(?i)\b([a-z0-9]{32})\b`),
}

var ErrNotAuthenticated = errors.New("gateway client is not authenticated")

type Option func(*Client)

func WithHTTPClient(client *http.Client) Option {
	return func(target *Client) {
		if client != nil {
			target.httpClient = client
		}
	}
}

type Client struct {
	baseURL    *url.URL
	username   string
	password   string
	httpClient *http.Client
	cookie     *http.Cookie
	token      string
}

func NewClient(baseURL, username, password string, options ...Option) (*Client, error) {
	if strings.TrimSpace(baseURL) == "" {
		baseURL = "http://192.168.1.1"
	}
	parsed, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("parse gateway URL: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, fmt.Errorf("gateway URL must use http or https")
	}
	if parsed.Host == "" {
		return nil, fmt.Errorf("gateway URL must include a host")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/")
	client := &Client{
		baseURL:  parsed,
		username: username,
		password: password,
		httpClient: &http.Client{
			Timeout: 15 * time.Second,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
	for _, option := range options {
		option(client)
	}
	return client, nil
}

func (client *Client) Login(ctx context.Context) error {
	if client.username == "" || client.password == "" {
		return errors.New("gateway username and password are required")
	}
	form := url.Values{"username": {client.username}, "psd": {client.password}}
	response, err := client.do(ctx, http.MethodPost, "/cgi-bin/luci", strings.NewReader(form.Encode()), false)
	if err != nil {
		return fmt.Errorf("login request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusFound {
		return fmt.Errorf("gateway rejected login: unexpected HTTP status %d", response.StatusCode)
	}
	for _, cookie := range response.Cookies() {
		if cookie.Name == "sysauth" {
			client.cookie = cookie
			break
		}
	}
	if client.cookie == nil || client.cookie.Value == "" {
		return errors.New("gateway login response did not include sysauth cookie")
	}

	body, err := client.getBytes(ctx, "/cgi-bin/luci")
	if err != nil {
		return fmt.Errorf("read session token: %w", err)
	}
	for _, pattern := range tokenPatterns {
		match := pattern.FindSubmatch(body)
		if len(match) == 2 {
			client.token = string(match[1])
			return nil
		}
	}
	return errors.New("gateway page did not contain a 32-character session token")
}

func (client *Client) Logout(ctx context.Context) error {
	if client.cookie == nil {
		return ErrNotAuthenticated
	}
	return client.post(ctx, "/cgi-bin/luci/admin/logout", nil)
}

func (client *Client) Status(ctx context.Context) (Status, error) {
	var value Status
	err := client.getJSON(ctx, "/cgi-bin/luci/admin/settings/gwstatus", &value)
	return value, err
}

func (client *Client) Info(ctx context.Context) (Info, error) {
	var value Info
	err := client.getJSON(ctx, "/cgi-bin/luci/admin/settings/gwinfo?get=all", &value)
	return value, err
}

func (client *Client) AllInfo(ctx context.Context) (AllInfo, error) {
	var value AllInfo
	err := client.getJSON(ctx, "/cgi-bin/luci/admin/allInfo", &value)
	return value, err
}

func (client *Client) PortMappings(ctx context.Context) (PortMappings, error) {
	var value PortMappings
	err := client.getJSON(ctx, "/cgi-bin/luci/admin/settings/pmDisplay", &value)
	return value, err
}

func (client *Client) AddPortMapping(ctx context.Context, mapping PortMapping) error {
	protocol, err := ParseProtocol(mapping.Protocol)
	if err != nil {
		return err
	}
	if strings.TrimSpace(mapping.Name) == "" || strings.TrimSpace(mapping.Client) == "" {
		return errors.New("port mapping name and client IP are required")
	}
	if err := validatePort(mapping.ExternalPort); err != nil {
		return fmt.Errorf("external port: %w", err)
	}
	if err := validatePort(mapping.InternalPort); err != nil {
		return fmt.Errorf("internal port: %w", err)
	}
	return client.post(ctx, "/cgi-bin/luci/admin/settings/pmSetSingle", url.Values{
		"op":       {"add"},
		"srvname":  {mapping.Name},
		"client":   {mapping.Client},
		"protocol": {string(protocol)},
		"exPort":   {fmt.Sprintf("%d", mapping.ExternalPort)},
		"inPort":   {fmt.Sprintf("%d", mapping.InternalPort)},
	})
}

func (client *Client) EnablePortMapping(ctx context.Context, name string) error {
	return client.portMappingAction(ctx, "enable", name)
}

func (client *Client) DisablePortMapping(ctx context.Context, name string) error {
	return client.portMappingAction(ctx, "disable", name)
}

func (client *Client) DeletePortMapping(ctx context.Context, name string) error {
	return client.portMappingAction(ctx, "del", name)
}

func (client *Client) Reboot(ctx context.Context) error {
	return client.post(ctx, "/cgi-bin/luci/admin/reboot", nil)
}

func (client *Client) portMappingAction(ctx context.Context, action, name string) error {
	if strings.TrimSpace(name) == "" {
		return errors.New("port mapping name is required")
	}
	return client.post(ctx, "/cgi-bin/luci/admin/settings/pmSetSingle", url.Values{
		"op":      {action},
		"srvname": {name},
	})
}

func (client *Client) getJSON(ctx context.Context, path string, target any) error {
	body, err := client.getBytes(ctx, path)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(body, target); err != nil {
		return fmt.Errorf("decode gateway response: %w", err)
	}
	return nil
}

func (client *Client) getBytes(ctx context.Context, path string) ([]byte, error) {
	response, err := client.do(ctx, http.MethodGet, path, nil, true)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("gateway returned HTTP status %d", response.StatusCode)
	}
	return readResponse(response.Body)
}

func (client *Client) post(ctx context.Context, path string, values url.Values) error {
	if client.cookie == nil || client.token == "" {
		return ErrNotAuthenticated
	}
	if values == nil {
		values = make(url.Values)
	}
	values.Set("token", client.token)
	response, err := client.do(ctx, http.MethodPost, path, strings.NewReader(values.Encode()), true)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("gateway returned HTTP status %d", response.StatusCode)
	}
	_, err = readResponse(response.Body)
	return err
}

func (client *Client) do(ctx context.Context, method, path string, body io.Reader, authenticated bool) (*http.Response, error) {
	reference, err := url.Parse(path)
	if err != nil {
		return nil, err
	}
	endpoint := client.baseURL.ResolveReference(reference)
	request, err := http.NewRequestWithContext(ctx, method, endpoint.String(), body)
	if err != nil {
		return nil, err
	}
	if method == http.MethodPost {
		request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	if authenticated {
		if client.cookie == nil {
			return nil, ErrNotAuthenticated
		}
		request.AddCookie(client.cookie)
	}
	return client.httpClient.Do(request)
}

func readResponse(reader io.Reader) ([]byte, error) {
	limited := io.LimitReader(reader, maxResponseBytes+1)
	body, err := io.ReadAll(limited)
	if err != nil {
		return nil, err
	}
	if len(body) > maxResponseBytes {
		return nil, fmt.Errorf("gateway response exceeded %d bytes", maxResponseBytes)
	}
	return body, nil
}

func validatePort(port int) error {
	if port < 1 || port > 65535 {
		return fmt.Errorf("must be between 1 and 65535")
	}
	return nil
}
