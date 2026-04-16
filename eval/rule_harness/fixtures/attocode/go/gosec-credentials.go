// Hand-curated fixture for gosec G101 (hardcoded credentials).

package config

import "os"

// --- GOOD: rule must NOT fire ---
var (
	PasswordEnvVar = "DATABASE_PASSWORD" // ok: G101-hardcoded-credentials
	apiKey         = os.Getenv("API_KEY") // ok: G101-hardcoded-credentials
)

// --- BAD: rule MUST fire ---
var DBPassword = "hunter2-supersecret" // expect: G101-hardcoded-credentials

const APIToken = "tok_abcd1234efgh5678" // expect: G101-hardcoded-credentials
