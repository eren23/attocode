// Correctness — true positives

function badPushSpread(source: number[], target: number[]) {
    target.push(...source);  // expect: typescript/ts-array-push-spread
}
