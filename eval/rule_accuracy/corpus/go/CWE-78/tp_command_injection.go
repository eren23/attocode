// Command injection — true positives for rule accuracy testing
package corpus

import "os/exec"

func badExecCommand(userInput string) {
	exec.Command("sh", "-c", userInput).Run() // expect: go-exec-command-var
}

func badExecCommandOutput(cmd string) {
	exec.Command(cmd).Output() // expect: go-exec-command-var
}
