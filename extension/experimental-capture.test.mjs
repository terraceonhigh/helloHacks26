import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);

test("Moodle capture keeps only mapper fields and never includes its session key", async () => {
  const {captureMoodle} = require("./providers/moodle.js");
  const calls = [];
  const capture = await captureMoodle({origin: "https://moodle.example.edu", sesskey: "fakekey123",
    now: new Date("2026-09-27T00:00:00Z"), fetch: async (url, init) => {
      calls.push({url, init});
      return {ok: true, json: async () => [
        {data: [{shortname: "CPSC101", fullname: "Intro", secret: "omit"}]},
        {data: {events: [{id: 9, name: "Quiz", modulename: "quiz", timesort: 1798000000,
          url: "https://moodle.example.edu/mod/quiz/view.php?id=9&token=omit",
          course: {shortname: "CPSC101", secret: "omit"}}]}}
      ]};
    }});
  assert.match(calls[0].url, /sesskey=fakekey123/);
  assert.equal(capture.courses[0].secret, undefined);
  assert.equal(capture.events[0].url, "https://moodle.example.edu/mod/quiz/view.php?id=9");
  assert.doesNotMatch(JSON.stringify(capture), /fakekey123|token|secret/);
});

test("Blackboard capture returns courses only and blocks foreign pagination", async () => {
  const {captureBlackboard} = require("./providers/blackboard.js");
  const capture = await captureBlackboard({origin: "https://bb.example.edu", fetch: async url => ({
    ok: true, json: async () => url.endsWith("/users/me") ? {id: "user1"} :
      url.includes("/users/user1/courses") ? {results: [{courseId: "_1_1"}]} :
      {id: "_1_1", courseId: "BIOL101", name: "Biology", term: {name: "Fall"}}
  })});
  assert.equal(capture.courses[0].courseId, "BIOL101");
  assert.equal(capture.items, undefined);
  await assert.rejects(captureBlackboard({origin: "https://bb.example.edu", fetch: async url => ({
    ok: true, json: async () => url.endsWith("/users/me") ? {id: "user1"} :
      {results: [], paging: {nextPage: "https://evil.example/steal"}}
  })}), /left its API origin/);
});

test("Piazza capture keeps pinned posts but drops ordinary posts", async () => {
  const {capturePiazza} = require("./providers/piazza.js");
  const capture = await capturePiazza({origin: "https://piazza.com", fetch: async (_url, init) => {
    const {method, params} = JSON.parse(init.body);
    const result = method === "user.status" ? {networks: [{id: "abc123", name: "Models"}]} :
      method === "network.get_my_feed" ? {feed: [{id: "post1"}, {id: "post2"}]} :
      params.cid === "post1" ? {id: "post1", tags: ["pin"], history: [{subject: "Room"}]} :
      {id: "post2", tags: [], history: [{subject: "Question"}]};
    return {ok: true, json: async () => ({result})};
  }});
  assert.equal(capture.networks[0].posts.length, 1);
  assert.equal(capture.networks[0].posts[0].history[0].subject, "Room");
});
