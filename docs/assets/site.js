document.addEventListener("DOMContentLoaded", () => {
  const targets = Array.from(
    document.querySelectorAll(
      ".hero-panel, .hero-card, .section-intro, .value-card, .runtime-card, .capability-card, .usecase-card, .docs-card, .path-card, .decision-card, .snippet-panel, .final-cta"
    )
  );

  targets.forEach((element, index) => {
    element.classList.add("reveal");
    element.style.setProperty("--reveal-delay", `${Math.min(index % 8, 7) * 55}ms`);
  });

  if (
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    typeof IntersectionObserver === "undefined"
  ) {
    targets.forEach((element) => element.classList.add("in-view"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) {
          continue;
        }
        entry.target.classList.add("in-view");
        observer.unobserve(entry.target);
      }
    },
    {
      rootMargin: "0px 0px -10% 0px",
      threshold: 0.12,
    }
  );

  targets.forEach((element) => observer.observe(element));
});
