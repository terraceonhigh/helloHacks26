// THROWAWAY: proves the js-tests CI job goes red on a failing JS assertion.
import { test } from "node:test";
import assert from "node:assert/strict";
test("deliberately failing assertion (ci-proof-red)", () => {
  assert.equal(1 + 1, 3);
});
