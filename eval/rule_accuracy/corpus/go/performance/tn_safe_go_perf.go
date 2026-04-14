// Performance — true negatives (safe patterns)
// no-expect: These should NOT trigger performance rules
package corpus

import "strings"

func safeEqualFold(a, b string) bool {
	return strings.EqualFold(a, b)
}

func safePrealloc(n int) []int {
	result := make([]int, 0, n)
	for i := 0; i < n; i++ {
		result = append(result, i)
	}
	return result
}
