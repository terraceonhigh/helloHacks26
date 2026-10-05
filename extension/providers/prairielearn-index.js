/* Experimental: read only links already rendered on the student's own home page. */
function capturePrairieLearnIndex(root = document) {
  const seen = new Set();
  const courses = [];
  for (const link of root.querySelectorAll('a[href^="/pl/course_instance/"]')) {
    const href = link.getAttribute("href") || "";
    const match = href.match(/^\/pl\/course_instance\/(\d+)(?:\/instructor)?\/?$/);
    if (!match || seen.has(match[1])) continue;
    seen.add(match[1]);
    courses.push({ci_id: match[1], title: link.textContent.trim()});
    if (courses.length > 100) throw new Error("PrairieLearn course limit exceeded");
  }
  if (!courses.length) throw new Error("No PrairieLearn course links found. Sign in and reopen the home page.");
  return courses;
}

if (typeof module !== "undefined") module.exports = {capturePrairieLearnIndex};
typeof document === "undefined" ? undefined : capturePrairieLearnIndex();
