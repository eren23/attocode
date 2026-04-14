// Performance — true negatives (safe patterns)
// no-expect: These should NOT trigger await-in-loop rules

async function safeParallel(urls: string[]) {
    const results = await Promise.all(urls.map(url => fetch(url)));
    return results;
}
