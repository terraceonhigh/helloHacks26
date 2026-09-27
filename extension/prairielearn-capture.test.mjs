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

test("PrairieLearn assessment rows accept an unstarted assessment's link", () => {
  const cell = (text, child = null) => ({textContent: text,
    querySelector: selector => selector.startsWith("a") || selector.startsWith("button") ? child : null});
  const link = {getAttribute: () => "/pl/course_instance/221053/assessment/9001/"};
  const row = {querySelector: () => null, querySelectorAll: () => [
    cell("Q3"), cell("Quiz 3", link), cell(""), cell("")
  ]};
  const root = {querySelectorAll: () => [row]};
  const result = capturePrairieLearnAssessments(root,
    "https://us.prairielearn.com/pl/course_instance/221053/assessments", () => ({querySelector: () => null}));
  assert.deepEqual(result.assessments, [{title: "Quiz 3", group: "", href: link.getAttribute(),
    due_text: "", score_text: "", credit_empty: true}]);
});

test("PrairieLearn assessment rows skip an unrecognized same-course link instead of throwing", () => {
  const cell = (text, child = null) => ({textContent: text,
    querySelector: selector => selector.startsWith("a") || selector.startsWith("button") ? child : null});
  const oddLink = {getAttribute: () => "/pl/course_instance/221053/some_new_type/1/"};
  const goodLink = {getAttribute: () => "/pl/course_instance/221053/assessment_instance/14835025/"};
  const oddRow = {querySelector: () => null, querySelectorAll: () => [cell("Q1"), cell("Odd", oddLink), cell(""), cell("")]};
  const goodRow = {querySelector: () => null, querySelectorAll: () => [cell("Q2"), cell("Quiz 2", goodLink), cell(""), cell("")]};
  const root = {querySelectorAll: () => [oddRow, goodRow]};
  const result = capturePrairieLearnAssessments(root,
    "https://us.prairielearn.com/pl/course_instance/221053/assessments", () => ({querySelector: () => null}));
  assert.deepEqual(result.assessments.map(a => a.title), ["Quiz 2"]);
});

test("PrairieLearn assessment rows still reject a link that left the course", () => {
  const cell = (text, child = null) => ({textContent: text,
    querySelector: selector => selector.startsWith("a") || selector.startsWith("button") ? child : null});
  const link = {getAttribute: () => "https://evil.example/steal"};
  const row = {querySelector: () => null, querySelectorAll: () => [cell("Q1"), cell("Evil", link), cell(""), cell("")]};
  const root = {querySelectorAll: () => [row]};
  assert.throws(() => capturePrairieLearnAssessments(root,
    "https://us.prairielearn.com/pl/course_instance/221053/assessments", () => ({querySelector: () => null})),
    /left the course/);
});
