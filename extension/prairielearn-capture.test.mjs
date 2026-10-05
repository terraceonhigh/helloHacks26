import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {capturePrairieLearnIndex} = require("./providers/prairielearn-index.js");
const {capturePrairieLearnAssessments} = require("./providers/prairielearn-assessments.js");

test("PrairieLearn index discovers distinct course instances without reading page HTML", () => {
  const links = [
    {getAttribute: () => "/pl/course_instance/221053", textContent: "CPSC 317: Internet Computing, 2026 Winter Term 1"},
    {getAttribute: () => "/pl/course_instance/221053/instructor", textContent: "duplicate"},
    {getAttribute: () => "/pl/course_instance/2/assessments", textContent: "wrong route"}
  ];
  const courses = capturePrairieLearnIndex({querySelectorAll: () => links});
  assert.deepEqual(courses, [{ci_id: "221053", title: links[0].textContent}]);
});

test("PrairieLearn assessment rows return selected fields, not the popover HTML", () => {
  const cell = (text, child = null) => ({textContent: text,
    querySelector: selector => selector.startsWith("a") || selector.startsWith("button") ? child : null});
  const link = {getAttribute: () => "/pl/course_instance/221053/assessment_instance/14835025/"};
  const popover = {getAttribute: () => "<table>secret markup</table>"};
  const heading = {querySelector: selector => selector === "th" ? {textContent: "Quizzes"} : null};
  const row = {querySelector: () => null, querySelectorAll: () => [
    cell("Q2"), cell("Quiz 2", link), cell("100% until Sunday", popover), cell("80%")
  ]};
  const root = {querySelectorAll: () => [heading, row]};
  const result = capturePrairieLearnAssessments(root,
    "https://us.prairielearn.com/pl/course_instance/221053/assessments",
    () => ({querySelector: () => ({textContent: "2026-09-27 23:59:59 (PDT)"})}));
  assert.equal(result.ci_id, "221053");
  assert.deepEqual(result.assessments, [{title: "Quiz 2", group: "Quizzes",
    href: link.getAttribute(), due_text: "2026-09-27 23:59:59 (PDT)",
    score_text: "80%", credit_empty: false}]);
  assert.doesNotMatch(JSON.stringify(result), /secret markup/);
});
