"use strict";

// Let the opening demonstrate the same decision model used in the full lesson.
const studio = document.getElementById("wes-studio");
if (studio) {
  const tabs = [...studio.querySelectorAll("[role=tab]")];
  const panels = [...studio.querySelectorAll("[role=tabpanel]")];
  const reel = studio.querySelector("video");
  const lesson = JSON.parse(document.getElementById("lesson-data").textContent);
  const preview = window.createTrainingLesson(lesson);
  const choices = document.getElementById("studio-choices");
  const feedback = document.getElementById("studio-feedback");

  // Reuse the source question and feedback so this preview cannot drift from the lesson.
  document.getElementById("studio-question").textContent = lesson.stages[0].question;
  for (const option of lesson.stages[0].options) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.label;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      const result = preview.choose(option.id);
      for (const sibling of choices.children) {
        sibling.setAttribute("aria-pressed", "false");
        sibling.removeAttribute("data-result");
      }
      button.setAttribute("aria-pressed", "true");
      button.dataset.result = result.correct ? "accepted" : "coaching";
      feedback.textContent = result.feedback;
      feedback.dataset.result = button.dataset.result;
    });
    choices.appendChild(button);
  }

  // Keep tabs usable by pointer and keyboard, with only the selected panel exposed.
  function selectTab(index, moveFocus = false) {
    tabs.forEach((tab, position) => {
      const selected = position === index;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      panels[position].hidden = !selected;
    });
    if (panels[index].id !== "studio-support") pauseCase();
    if (panels[index].id !== "studio-results") reel.pause();
    if (moveFocus) tabs[index].focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(index));
    tab.addEventListener("keydown", event => {
      let next = index;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(next, true);
    });
  });

  // Animate only documented events, without inventing the troubleshooting steps.
  const support = document.getElementById("support-case");
  const play = document.getElementById("support-play");
  const pause = document.getElementById("support-pause");
  const status = document.getElementById("support-status");
  const progress = document.getElementById("support-progress");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const announcements = ["Access problem", "Access restored", "Instructor acknowledgement"];
  let elapsed = 0;
  let started = 0;
  let timer = null;
  let previousStep = -1;

  function renderCase() {
    const step = Math.min(2, Math.floor(elapsed / 4000));
    support.dataset.step = String(step);
    progress.style.width = `${Math.min(100, elapsed / 120)}%`;
    if (step !== previousStep) {
      status.textContent = announcements[step];
      previousStep = step;
    }
  }
  function pauseCase() {
    if (timer === null) return;
    elapsed = Math.min(12000, elapsed + performance.now() - started);
    clearInterval(timer);
    timer = null;
    renderCase();
    pause.hidden = true;
    play.textContent = elapsed >= 12000 ? "Replay support case" : "Resume support case";
  }
  function playCase() {
    if (timer !== null) return;
    if (reduced.matches) {
      support.dataset.step = "all";
      status.textContent = "All three documented events shown without animation";
      progress.style.width = "100%";
      play.textContent = "Show support case";
      return;
    }
    if (elapsed >= 12000) { elapsed = 0; previousStep = -1; }
    started = performance.now();
    pause.hidden = false;
    play.textContent = "Playing support case";
    renderCase();
    timer = setInterval(() => {
      const duration = elapsed + performance.now() - started;
      const saved = elapsed;
      elapsed = Math.min(12000, duration);
      renderCase();
      elapsed = saved;
      if (duration >= 12000) pauseCase();
    }, 120);
  }
  play.addEventListener("click", playCase);
  pause.addEventListener("click", pauseCase);
  reduced.addEventListener("change", () => {
    pauseCase();
    if (reduced.matches) {
      support.dataset.step = "all";
      progress.style.width = "100%";
      play.textContent = "Show support case";
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pauseCase();
  });
  selectTab(0);
  if (reduced.matches) support.dataset.step = "all";
}
