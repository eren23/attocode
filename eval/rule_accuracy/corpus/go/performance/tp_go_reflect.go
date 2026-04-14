// Reflection and mutex — true positives
package corpus

import (
	"reflect"
	"sync"
)

func badReflectLoop(items []interface{}) {
	for _, item := range items {
		t := reflect.TypeOf(item)  // expect: go/go-reflect-in-loop
		fmt.Println(t.Name())
	}
}

func badMutexIO(mu *sync.Mutex) {
	mu.Lock()  // expect: go/go-mutex-lock
	writeToFile("data")
	mu.Unlock()
}
