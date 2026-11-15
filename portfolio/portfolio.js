"use strict";
// Explain the selected answer so the check teaches rather than merely scoring it.
const form = document.getElementById("check-form");
const feedback = document.getElementById("check-feedback");
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const selected = new FormData(form).get("answer");
  const responses = {
    half: "Correct. z = (130 - 100) / 30 = 1. The score is one standard deviation " +
      "above the mean. Its percentile falls from about 97.72 to 84.13, while the " +
      "proportion above it rises from about 2.28% to 15.87%.",
    same: "The raw score stays at 130, but a z-score also depends on the spread. " +
      "Divide its 30-point distance from the mean by the new standard deviation " +
      "of 30. Try the first explanation.",
    double: "The standard deviation is the denominator in z = (X - μ) / σ. " +
      "Doubling the denominator halves the z-score when X and μ stay fixed. " +
      "Check the activity's numerical readout, then try again."
  };
  feedback.textContent = responses[selected] || "Choose an explanation first, then check it.";
});

// Give feedback for each decision, then explain the next check in the real workflow.
