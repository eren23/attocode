// Style issues — true positives

function badAnyType(data: any) {  // expect: typescript/ts-any-type
    const result: any = process(data);  // expect: typescript/ts-any-type
    console.log(result);  // expect: typescript/ts-console-log
    return result;
}

function badConsole() {
    console.log("debug");  // expect: typescript/ts-console-log
}
