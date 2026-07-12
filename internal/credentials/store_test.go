package credentials

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

type memorySecrets struct {
	values map[string]string
}

func newMemorySecrets() *memorySecrets {
	return &memorySecrets{values: make(map[string]string)}
}

func (store *memorySecrets) Set(service, account, secret string) error {
	store.values[service+"\x00"+account] = secret
	return nil
}

func (store *memorySecrets) Get(service, account string) (string, error) {
	secret, ok := store.values[service+"\x00"+account]
	if !ok {
		return "", errors.New("not found")
	}
	return secret, nil
}

func (store *memorySecrets) Delete(service, account string) error {
	delete(store.values, service+"\x00"+account)
	return nil
}

func TestStoreRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "profile.json")
	secrets := newMemorySecrets()
	store := NewStore(path, secrets)
	profile := Profile{URL: "http://192.0.2.1/", Username: "example-user"}
	if err := store.Save(profile, "example-pass"); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := info.Mode().Perm(); got != 0o600 {
		t.Fatalf("profile mode = %o", got)
	}
	loaded, err := store.Load()
	if err != nil {
		t.Fatal(err)
	}
	if loaded.URL != "http://192.0.2.1" || loaded.Username != profile.Username {
		t.Fatalf("unexpected profile: %#v", loaded)
	}
	password, err := store.Password(loaded)
	if err != nil || password != "example-pass" {
		t.Fatalf("Password() = %q, %v", password, err)
	}
	if err := store.Delete(); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Load(); !errors.Is(err, ErrNoProfile) {
		t.Fatalf("Load() after delete = %v", err)
	}
}

func TestStoreRejectsIncompleteProfile(t *testing.T) {
	store := NewStore(filepath.Join(t.TempDir(), "profile.json"), newMemorySecrets())
	if err := store.Save(Profile{URL: "http://192.0.2.1"}, "example-pass"); err == nil {
		t.Fatal("expected missing username error")
	}
}
