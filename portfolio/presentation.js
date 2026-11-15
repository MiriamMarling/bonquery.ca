"use strict";
// Let the navigation show which work sample is in view without changing the URL.
const sectionLinks = [...document.querySelectorAll(".nav a[href^='#']")];
if ("IntersectionObserver" in window) {
  const visibleSections = new Map();
  const navObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) visibleSections.set(entry.target.id, entry);
      else visibleSections.delete(entry.target.id);
    }
    const visible = [...visibleSections.values()]
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    for (const link of sectionLinks) {
      if (visible && link.hash === `#${visible.target.id}`) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
  }, {rootMargin: "-12% 0px -45% 0px", threshold: [0, .15, .4]});
  for (const link of sectionLinks) {
    const section = document.querySelector(link.hash);
    if (section) navObserver.observe(section);
  }

  // Give each sample one restrained entrance, while keeping all content readable.
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const entranceObserver = new IntersectionObserver((entries, observer) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("sample-entered");
          observer.unobserve(entry.target);
        }
      }
    }, {threshold: .08});
    for (const sample of document.querySelectorAll(
      ".hero-studio, .training-shell, .course-story figure, .source-panel, .guide-cover")) {
      entranceObserver.observe(sample);
    }
  }
}

// Reveal the linked walkthrough before the browser moves to its anchor.
function revealWalkthrough() {
  const walkthrough = document.getElementById("training-demo");
  if (walkthrough && location.hash === "#training-demo") walkthrough.open = true;
}
for (const link of document.querySelectorAll('a[href="#training-demo"]')) {
  link.addEventListener("click", () => {
    document.getElementById("training-demo").open = true;
  });
}
window.addEventListener("hashchange", revealWalkthrough);
revealWalkthrough();
