package credentials

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	keyring "github.com/zalando/go-keyring"
)

const serviceName = "ctgw"

var ErrNoProfile = errors.New("no stored ctgw profile")

type Profile struct {
	URL      string `json:"url"`
	Username string `json:"username"`
}

type SecretStore interface {
	Set(service, account, secret string) error
	Get(service, account string) (string, error)
	Delete(service, account string) error
}

type systemKeyring struct{}

func (systemKeyring) Set(service, account, secret string) error {
	return keyring.Set(service, account, secret)
}

func (systemKeyring) Get(service, account string) (string, error) {
	return keyring.Get(service, account)
}

func (systemKeyring) Delete(service, account string) error {
	return keyring.Delete(service, account)
}

type Store struct {
	profilePath string
	secrets     SecretStore
}

func New() (*Store, error) {
	configDir, err := os.UserConfigDir()
	if err != nil {
		return nil, fmt.Errorf("locate user config directory: %w", err)
	}
	return NewStore(filepath.Join(configDir, "ctgw", "profile.json"), systemKeyring{}), nil
}

func NewStore(profilePath string, secrets SecretStore) *Store {
	return &Store{profilePath: profilePath, secrets: secrets}
}

func (store *Store) Load() (Profile, error) {
	file, err := os.Open(store.profilePath)
	if errors.Is(err, os.ErrNotExist) {
		return Profile{}, ErrNoProfile
	}
	if err != nil {
		return Profile{}, fmt.Errorf("open stored profile: %w", err)
	}
	defer file.Close()
	var profile Profile
	decoder := json.NewDecoder(io.LimitReader(file, 64<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&profile); err != nil {
		return Profile{}, fmt.Errorf("decode stored profile: %w", err)
	}
	if err := validateProfile(profile); err != nil {
		return Profile{}, fmt.Errorf("invalid stored profile: %w", err)
	}
	return profile, nil
}

func (store *Store) Save(profile Profile, password string) error {
	if err := validateProfile(profile); err != nil {
		return err
	}
	if password == "" {
		return errors.New("password is required")
	}
	profile.URL = strings.TrimRight(profile.URL, "/")
	if err := os.MkdirAll(filepath.Dir(store.profilePath), 0o700); err != nil {
		return fmt.Errorf("create user config directory: %w", err)
	}
	if err := os.Chmod(filepath.Dir(store.profilePath), 0o700); err != nil {
		return fmt.Errorf("protect user config directory: %w", err)
	}
	encoded, err := json.MarshalIndent(profile, "", "  ")
	if err != nil {
		return fmt.Errorf("encode profile: %w", err)
	}
	encoded = append(encoded, '\n')
	temporary := store.profilePath + ".tmp"
	if err := os.WriteFile(temporary, encoded, 0o600); err != nil {
		return fmt.Errorf("write profile: %w", err)
	}
	if err := os.Chmod(temporary, 0o600); err != nil {
		_ = os.Remove(temporary)
		return fmt.Errorf("protect profile: %w", err)
	}
	account := accountName(profile)
	if err := store.secrets.Set(serviceName, account, password); err != nil {
		_ = os.Remove(temporary)
		return fmt.Errorf("store password in system keyring: %w", err)
	}
	if err := os.Rename(temporary, store.profilePath); err != nil {
		_ = store.secrets.Delete(serviceName, account)
		_ = os.Remove(temporary)
		return fmt.Errorf("activate stored profile: %w", err)
	}
	return nil
}

func (store *Store) Password(profile Profile) (string, error) {
	secret, err := store.secrets.Get(serviceName, accountName(profile))
	if err != nil {
		return "", fmt.Errorf("read password from system keyring: %w", err)
	}
	return secret, nil
}

func (store *Store) Delete() error {
	profile, err := store.Load()
	if err != nil {
		return err
	}
	if err := store.secrets.Delete(serviceName, accountName(profile)); err != nil && !errors.Is(err, keyring.ErrNotFound) {
		return fmt.Errorf("delete password from system keyring: %w", err)
	}
	if err := os.Remove(store.profilePath); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("delete stored profile: %w", err)
	}
	return nil
}

func (store *Store) Path() string {
	return store.profilePath
}

func accountName(profile Profile) string {
	return profile.Username + "@" + strings.TrimRight(profile.URL, "/")
}

func validateProfile(profile Profile) error {
	if strings.TrimSpace(profile.URL) == "" {
		return errors.New("gateway URL is required")
	}
	if strings.TrimSpace(profile.Username) == "" {
		return errors.New("gateway username is required")
	}
	return nil
}
