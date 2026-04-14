// Template XSS — true positives
package corpus

import "html/template"

func badTemplate(userInput string) template.HTML {
	return template.HTML(userInput)  // expect: go/go-template-html-unescaped
}
