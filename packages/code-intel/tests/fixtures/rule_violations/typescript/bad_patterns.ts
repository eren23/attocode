// TypeScript file with intentional rule violations for testing.
//
// Each violation is annotated with // expect: <rule-id> on the same line.

import { fetchUser, fetchOrder } from './api';

async function loadAll(ids: string[]) {
  // Builtin: sequential await in loop
  for (const id of ids) {
    const data = await fetchUser(id); // expect: ts-await-in-loop
    console.log(data); // expect: ts-console-log
  }
}

function getStatus(response: unknown): string {
  // Team preference: no cast to any
  const data = response as any; // expect: ts-no-any-cast
  return data.status;
}

function cleanFunction(x: number): number {
  // This function should produce NO findings
  return x * 2;
}
