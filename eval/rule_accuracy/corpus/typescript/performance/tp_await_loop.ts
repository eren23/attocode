// Performance — true positives

async function badAwaitLoop(urls: string[]) {
    for (const url of urls) {
        const result = await fetch(url);  // expect: typescript/ts-await-in-loop
        console.log(result);
    }
}
