# Security policy

Please report vulnerabilities privately through GitHub Security Advisories. Do not open a public issue containing gateway credentials, session cookies, tokens, serial numbers, WAN account names, MAC addresses, SSIDs, or unredacted gateway responses.

This project interacts with a device administration interface. Test against hardware you own or are authorized to manage, inspect current state before applying changes, and keep a separate recovery path available.

`ctgw auth login` stores passwords in the current OS user's system keyring. The profile file contains only the gateway URL and username and is created with user-only permissions. Environment variables remain available for automation, but may be observable to other processes running as the same user.
