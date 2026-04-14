// Performance issues — true positives
package corpus

import (
	"fmt"
	"strings"
)

func badSprintf(id int) string {
	return fmt.Sprintf("key:%d", id)  // expect: go/go-sprintf-allocation
}

func badToLowerCompare(a, b string) bool {
	return strings.ToLower(a) == strings.ToLower(b)  // expect: go/go-string-tolower-compare
}
