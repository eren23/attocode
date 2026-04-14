// Correctness issues — true positives
package corpus

import "fmt"

func badErrorCompare(err error) bool {
	return err.Error() == "not found"  // expect: go/go-error-string-compare
}

func badDeferInLoop(items []string) {
	for _, item := range items {
		f := openFile(item)
		defer f.Close()  // expect: go/go-defer-statement
		process(f)
	}
}
