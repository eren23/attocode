// TLS — true negatives (safe patterns)
// no-expect: These should NOT trigger TLS insecure rules
package corpus

import "crypto/tls"

func safeTLSConfig() *tls.Config {
	return &tls.Config{
		MinVersion: tls.VersionTLS12,
	}
}
