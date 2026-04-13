// Go file with intentional rule violations for testing.
//
// Each violation is annotated with // expect: <rule-id> on the same line.
package main

import (
	"fmt"
	"strings"
)

func init() { // expect: go-no-init-function
	fmt.Println("initializing")
}

func HandleRequest(name string) string {
	// Team preference: no panic
	if name == "" {
		panic("name cannot be empty") // expect: go-no-panic
	}

	// Builtin: string comparison without EqualFold
	if strings.ToLower(name) == "admin" { // expect: go-string-tolower-compare
		return "admin dashboard"
	}

	// Builtin: error string comparison
	return fmt.Sprintf("hello %s", name) // expect: go-sprintf-allocation
}

func CleanFunction(x int) int {
	// This function should produce NO findings
	return x * 2
}
