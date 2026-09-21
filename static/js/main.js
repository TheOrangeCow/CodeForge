document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".flash").forEach((el) => {
        el.style.cursor = "pointer";
        el.title = "Click to dismiss";
        el.addEventListener("click", () => {
            el.style.transition = "opacity 0.15s ease";
            el.style.opacity = "0";
            setTimeout(() => el.remove(), 150);
        });
    });

    document.querySelectorAll(".star-form").forEach((form) => {
        const stars = Array.from(form.querySelectorAll(".star-btn"));
        stars.forEach((btn, idx) => {
            btn.addEventListener("mouseenter", () => {
                stars.forEach((s, i) => s.classList.toggle("star-on", i <= idx));
            });
        });
        form.addEventListener("mouseleave", () => {
            stars.forEach((s) => {
                if (!s.dataset.locked) return;
            });
        });
    });
});
