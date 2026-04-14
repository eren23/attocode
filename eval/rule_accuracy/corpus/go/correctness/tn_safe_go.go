// Correctness — true negatives (safe patterns)
// no-expect: These should NOT trigger correctness rules
package corpus

import "errors"

var ErrNotFound = errors.New("not found")

func safeErrorIs(err error) bool {
	return errors.Is(err, ErrNotFound)
}

func safeDeferOutsideLoop() {
	f := openFile("data.txt")
	defer f.Close()
	process(f)
}
