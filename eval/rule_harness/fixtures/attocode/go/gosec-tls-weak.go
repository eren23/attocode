// Hand-curated fixture for gosec G402 (weak TLS) and G401 (weak cipher).

package secure

import (
	"crypto/aes"
	"crypto/des"
	"crypto/rc4"
	"crypto/tls"
)

func goodTLS() *tls.Config {
	// --- GOOD: TLS 1.2 minimum ---
	return &tls.Config{MinVersion: tls.VersionTLS12} // ok: G402-tls-min-version
}

func badTLS() *tls.Config {
	// --- BAD: SSLv3 ---
	return &tls.Config{MinVersion: tls.VersionSSL30} // expect: G402-tls-min-version
}

func badTLS10() *tls.Config {
	return &tls.Config{MinVersion: tls.VersionTLS10} // expect: G402-tls-min-version
}

func goodAES(key []byte) {
	_, _ = aes.NewCipher(key) // ok: G401-weak-cipher
}

func badDES(key []byte) {
	_, _ = des.NewCipher(key) // expect: G401-weak-cipher
}

func badRC4(key []byte) {
	_, _ = rc4.NewCipher(key) // expect: G401-weak-cipher
}
