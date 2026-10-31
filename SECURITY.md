# Security policy

Report vulnerabilities privately through GitHub Security Advisories. Do not post credentials, cookies, tokens, device identifiers, WAN accounts or raw gateway responses in public issues.

Treat devices as production equipment. Use only authorized hardware, inspect state before changes and preserve a recovery path. Every write requires --yes; mapping writes verify the target and unchanged unrelated rules. An uncertain result must not be retried automatically.

Passwords are stored only in the current user's native Keychain, Credential Manager or Secret Service. There is no plaintext fallback. Profiles contain URL and username only; POSIX modes are 0700/0600 and Windows uses inherited user ACLs. Process environment credentials may be observable to other processes running as the same user.

Default info output redacts known sensitive fields, but device lists and mappings remain private. HTTP management endpoints do not encrypt credentials; use a trusted network or secure tunnel. Redirects are refused and raw error responses are withheld. Standard Python proxy settings apply. Tests and CI use synthetic devices and do not prove real-device or native-keyring acceptance.
