import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {captureCanvas} = require("./providers/canvas.js");

test("captures minimum Canvas JSON and strips secret URL parameters", async () => {
  const paths = [];
  const request = async (url, options) => {
    const parsed = new URL(url);
    paths.push(parsed.pathname);
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.redirect, "error");
    const body = parsed.pathname === "/api/v1/courses" ? [
      {id: 7, course_code: "CPSC 121", name: "Models", term: {name: "2026W1"},
       enrollments: [{computed_current_score: 88}], student_id: "must-not-upload"}
    ] : parsed.pathname === "/api/v1/planner/items" ? [
      {course_id: 7, plannable_type: "quiz", plannable_date: "2026-09-30T06:59:00Z",
       plannable: {title: "Quiz 2", private_notes: "must-not-upload"},
       html_url: "/courses/7/quizzes/3?access_token=must-not-upload",
       submissions: {submitted: false, excused: false},
       planner_override: {marked_complete: false}}
    ] : [
      {name: "Reading", due_at: null, html_url: "/courses/7/assignments/9",
       has_submitted_submissions: true, secret: "must-not-upload"}
    ];
    return {ok: true, status: 200, text: async () => `while(1);${JSON.stringify(body)}`,
            headers: {get: () => null}};
  };
  const capture = await captureCanvas({origin: "https://canvas.ubc.ca", fetch: request,
                                       now: new Date("2026-09-27T12:00:00Z")});
  assert.deepEqual(paths, ["/api/v1/courses", "/api/v1/planner/items",
                           "/api/v1/courses/7/assignments"]);
  assert.equal(capture.courses[0].term.name, "2026W1");
  assert.equal(capture.planner[0].html_url, "https://canvas.ubc.ca/courses/7/quizzes/3");
  assert.equal(capture.undated[0].has_submitted_submissions, true);
  assert.ok(!JSON.stringify(capture).includes("must-not-upload"));
});

test("rejects a pagination link that would carry browser credentials off origin", async () => {
  const request = async () => ({ok: true, status: 200, text: async () => "[]",
    headers: {get: () => '<https://evil.example/api/v1/courses>; rel="next"'}});
  await assert.rejects(captureCanvas({origin: "https://canvas.ubc.ca", fetch: request}),
                       /allowed origin/);
});

test("completed planner submission survives the Canvas capture", async () => {
  const request = async url => ({ok: true, status: 200, headers: {get: () => null},
    text: async () => JSON.stringify(new URL(url).pathname === "/api/v1/planner/items" ? [
      {course_id: 7, plannable_type: "quiz", plannable_date: "2026-09-30T06:59:00Z",
       plannable: {title: "Quiz 2"}, html_url: "/courses/7/quizzes/3",
       submissions: {submitted: true}, planner_override: {marked_complete: false}}
    ] : [])});
  const capture = await captureCanvas({origin: "https://canvas.ubc.ca", fetch: request});
  assert.deepEqual(capture.planner[0].submissions, {submitted: true, excused: false});
});
