/* One entry per verified browser capture adapter. The background transport and
   popup use this registry without branching on a provider name. */
const HUB_PROVIDERS = Object.freeze([
  {id: "canvas", label: "Canvas", origin: "https://canvas.ubc.ca",
   tabPattern: "https://canvas.ubc.ca/*", captureFile: "providers/canvas.js"},
  {id: "moodle", label: "Moodle (experimental)", customOrigin: true,
   captureFile: "providers/moodle.js", pageSessionPath: ["M", "cfg", "sesskey"]},
  {id: "blackboard", label: "Blackboard (experimental, courses only)", customOrigin: true,
   captureFile: "providers/blackboard.js"},
  {id: "piazza", label: "Piazza (experimental)", origin: "https://piazza.com",
   tabPattern: "https://piazza.com/*", captureFile: "providers/piazza.js"},
  {id: "prairielearn", label: "PrairieLearn (experimental)",
   origin: "https://us.prairielearn.com", tabPattern: "https://us.prairielearn.com/*",
   indexFile: "providers/prairielearn-index.js",
   pageFile: "providers/prairielearn-assessments.js",
   courseIdField: "ci_id", courseIdPattern: /^\d+$/,
   pagePathTemplate: "/pl/course_instance/{id}/assessments", rowsKey: "assessments"}
]);
globalThis.HUB_PROVIDERS = HUB_PROVIDERS;
if (typeof module !== "undefined") module.exports = {HUB_PROVIDERS};
