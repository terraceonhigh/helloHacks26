/* Experimental: select text fields from rendered rows; raw HTML never leaves the tab.
   ponytail: PrairieLearn-only rule-6 DOM exception. Use a student JSON API if one becomes available. */
function capturePrairieLearnAssessments(root = document, pageUrl = location.href,
                                       parseHtml = html => new DOMParser().parseFromString(html, "text/html")) {
  const page = new URL(pageUrl);
  const match = page.pathname.match(/^\/pl\/course_instance\/(\d+)\/assessments\/?$/);
  if (page.origin !== "https://us.prairielearn.com" || !match) {
    throw new Error("Open a PrairieLearn assessments page to capture rows");
  }
  const assessments = [];
  let group = "";
  for (const row of root.querySelectorAll("table tbody tr")) {
    const heading = row.querySelector("th");
    if (heading) {
      group = heading.textContent.trim();
      continue;
    }
    const cells = row.querySelectorAll("td");
    if (cells.length < 3) continue;
    const title = cells[1].textContent.trim();
    const link = cells[1].querySelector("a[href]");
    const href = link?.getAttribute("href") || "";
    // An unstarted assessment usually links to .../assessment/<id>/, not
    // .../assessment_instance/<id>/ - accept both (PM review on #87/#97).
    // A link outside this course's own path is a real safety issue and
    // still rejected; a same-course link whose shape we just don't
    // recognize is skipped instead of throwing away the whole capture.
    if (href && !href.startsWith(`/pl/course_instance/${match[1]}/`)) {
      throw new Error("PrairieLearn assessment link left the course");
    }
    if (href && !new RegExp(`^/pl/course_instance/${match[1]}/assessment(?:_instance)?/\\d+/?$`).test(href)) {
      continue;
    }
    const popover = cells[2].querySelector("button[data-bs-content]");
    const popoverHtml = popover?.getAttribute("data-bs-content") || "";
    const dueText = popoverHtml ?
      parseHtml(popoverHtml).querySelector("tr:nth-child(2) td:nth-child(3)")?.textContent.trim() || "" : "";
    assessments.push({title, group, href, due_text: dueText,
      score_text: cells[3]?.textContent.trim() || "",
      credit_empty: !popover && cells[2].textContent.trim() === ""});
    if (assessments.length > 300) throw new Error("PrairieLearn assessment limit exceeded");
  }
  return {ci_id: match[1], assessments};
}

if (typeof module !== "undefined") module.exports = {capturePrairieLearnAssessments};
typeof document === "undefined" ? undefined : capturePrairieLearnAssessments();
