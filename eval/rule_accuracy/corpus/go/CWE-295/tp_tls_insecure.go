// TLS insecure — true positives for rule accuracy testing
package corpus

import "crypto/tls"

func badTLSConfig() *tls.Config {
	return &tls.Config{
		InsecureSkipVerify: true,  // expect: go/go-tls-insecure
	}
}
