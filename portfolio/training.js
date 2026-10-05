"use strict";
// Keep lesson decisions and feedback in one model for the interface and verification.
window.createTrainingLesson = function (data) {
  let step = 0;
  let accepted = false;
  let complete = false;
  let firstChoices = [];
  let selected = null;
  return {
    state() { return {step, accepted, complete, selected, firstChoices: [...firstChoices]}; },
    choose(id) {
      if (complete) throw new Error("The practice is complete. Start again to retry.");
      const option = data.stages[step].options.find(item => item.id === id);
      if (!option) throw new Error("Unknown lesson choice.");
      if (firstChoices[step] === undefined) firstChoices[step] = option.correct;
      accepted = option.correct;
      selected = id;
      return option;
    },
    next() {
      if (!accepted || complete) return false;
      if (step === data.stages.length - 1) complete = true;
      else { step += 1; accepted = false; selected = null; }
      return true;
    },
    restart() {
      step = 0; accepted = false; complete = false; firstChoices = []; selected = null;
    }
  };
};

// Keep practice state in memory. Nothing is submitted to a course or reporting service.
const trainingRoot = document.getElementById("training-root");
if (trainingRoot) {
  const data = JSON.parse(document.getElementById("lesson-data").textContent);
  const model = window.createTrainingLesson(data);
  const title = document.getElementById("lesson-question");
  const context = document.getElementById("lesson-context");
  const choices = document.getElementById("lesson-choices");
  const feedback = document.getElementById("lesson-feedback");
  const next = document.getElementById("lesson-next");
  const stagePanel = document.getElementById("lesson-stage");
  const summary = document.getElementById("lesson-summary");
  const progress = document.getElementById("lesson-progress");
  const stepLabels = [...document.querySelectorAll("[data-lesson-step]")];

  function render(moveFocus = false) {
    const state = model.state();
    progress.textContent = state.complete ? "Practice complete" :
      `Decision ${state.step + 1} of ${data.stages.length}`;
    stepLabels.forEach((label, index) => {
      label.classList.toggle("done", state.complete || index < state.step);
      label.classList.toggle("current", !state.complete && index === state.step);
      if (!state.complete && index === state.step) label.setAttribute("aria-current", "step");
      else label.removeAttribute("aria-current");
    });
    stagePanel.hidden = state.complete;
    summary.hidden = !state.complete;
    if (state.complete) {
      const correct = state.firstChoices.filter(Boolean).length;
      document.getElementById("lesson-score").textContent =
        `${correct} of ${data.stages.length} decisions correct on the first choice in this run.`;
      if (moveFocus) document.getElementById("lesson-summary-title").focus({preventScroll: true});
      return;
    }
    const stage = data.stages[state.step];
    title.textContent = stage.question;
    choices.replaceChildren();
    context.replaceChildren();
    const caption = document.createElement("p");
    caption.className = "practice-label";
    caption.textContent = stage.image ? "Actual interface crop from the TA guide" :
      "Illustrative practice preview";
    context.appendChild(caption);
    if (stage.image) {
      const image = document.createElement("img");
      image.src = `assets/${stage.image}`;
      image.alt = stage.image_alt;
      context.appendChild(image);
      const sourceCue = document.createElement("p");
      sourceCue.className = "source-cue";
      sourceCue.textContent = stage.source_label;
      context.appendChild(sourceCue);
    } else {
      const preview = document.createElement("div");
      preview.className = "preview-counts";
      for (const text of ["3 source rows", "2 matched learners", "1 mismatch to investigate"]) {
        const item = document.createElement("p");
        item.textContent = text;
        preview.appendChild(item);
      }
      context.appendChild(preview);
    }
    feedback.textContent = "";
    feedback.className = "lesson-feedback";
    next.disabled = true;
    next.textContent = state.step === data.stages.length - 1 ? "Finish and take the job aid" :
      "Next decision →";
    for (const option of stage.options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "lesson-choice";
      button.textContent = option.label;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => {
        const result = model.choose(option.id);
        for (const sibling of choices.children) {
          sibling.setAttribute("aria-pressed", "false");
          sibling.removeAttribute("data-result");
        }
        button.setAttribute("aria-pressed", "true");
        button.setAttribute("data-result", result.correct ? "accepted" : "coaching");
        feedback.textContent = result.feedback;
        feedback.className = `lesson-feedback ${result.correct ? "accepted" : "coaching"}`;
        next.disabled = !model.state().accepted;
      });
      choices.appendChild(button);
    }
    if (moveFocus) title.focus({preventScroll: true});
  }

  // Let learners retry freely and return to the job aid at any point.
  next.addEventListener("click", () => { if (model.next()) render(true); });
  document.getElementById("lesson-restart").addEventListener("click", () => {
    model.restart(); render(true);
  });
  render();
}
