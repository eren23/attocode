// Style — true negatives (safe patterns)
// no-expect: These should NOT trigger style rules

function safeTyped(data: string): number {
    return parseInt(data, 10);
}

function safeLogger(msg: string) {
    logger.info(msg);
}
