(() => {
  const dot = document.getElementById("cursorDot");
  const follow = document.getElementById("cursorFollow");
  if (!dot || !follow) return;

  const style = document.createElement("style");
  style.id = "reference-homepage-cursor";
  style.textContent = `
    .cursor-dot {
      position: fixed !important;
      left: 0 !important;
      top: 0 !important;
      width: 10px !important;
      height: 10px !important;
      margin: -5px 0 0 -5px !important;
      border: 0 !important;
      border-radius: 50% !important;
      background: #fff !important;
      box-shadow: none !important;
      opacity: 0 !important;
      transform: none !important;
      pointer-events: none !important;
      z-index: 10087 !important;
    }

    .cursor-dot.cursor-visible { opacity: 1 !important; }

    .cursor-follow {
      position: fixed !important;
      left: 0 !important;
      top: 0 !important;
      width: 18px !important;
      height: 18px !important;
      margin: 0 !important;
      border: 0 !important;
      border-radius: 25px !important;
      background: #fff !important;
      box-shadow: none !important;
      opacity: .25 !important;
      transform: scale(1) !important;
      pointer-events: none !important;
      z-index: 10086 !important;
      transition: .2s ease-in-out !important;
      transition-property: background, opacity, transform !important;
    }

    .cursor-follow.hidden { opacity: 0 !important; }
    .cursor-follow.active {
      opacity: .5 !important;
      transform: scale(.5) !important;
    }

    @media (max-width: 720px), (pointer: coarse) {
      .cursor-dot,
      .cursor-follow { display: none !important; }
    }
  `;
  document.head.appendChild(style);

  dot.classList.remove("cursor-visible");
  follow.classList.remove("cursor-visible", "pressed", "active");
  follow.classList.add("hidden");

  let curr = null;
  let prev = null;
  let raf = 0;

  const moveDot = (x, y) => {
    dot.style.translate = `${x}px ${y}px`;
  };

  const moveFollow = (x, y) => {
    follow.style.translate = `${x}px ${y}px`;
  };

  const render = () => {
    raf = 0;
    if (!curr) return;

    if (prev) {
      prev.x += (curr.x - prev.x) * 0.35;
      prev.y += (curr.y - prev.y) * 0.35;
      moveFollow(prev.x, prev.y);
    } else {
      prev = { ...curr };
      moveFollow(prev.x, prev.y);
    }

    if (Math.abs(curr.x - prev.x) > 0.01 || Math.abs(curr.y - prev.y) > 0.01) {
      raf = requestAnimationFrame(render);
    }
  };

  const queueRender = () => {
    if (!raf) raf = requestAnimationFrame(render);
  };

  document.addEventListener("mousemove", (event) => {
    moveDot(event.clientX, event.clientY);
    dot.classList.add("cursor-visible");

    if (curr === null) moveFollow(event.clientX - 8, event.clientY - 8);
    curr = { x: event.clientX - 8, y: event.clientY - 8 };
    follow.classList.remove("hidden");
    follow.classList.add("cursor-visible");
    queueRender();
  }, { passive: true });

  document.addEventListener("mouseenter", () => {
    dot.classList.add("cursor-visible");
    follow.classList.remove("hidden");
  });

  document.addEventListener("mouseleave", () => {
    dot.classList.remove("cursor-visible");
    follow.classList.add("hidden");
  });

  document.addEventListener("mousedown", () => follow.classList.add("active"));
  document.addEventListener("mouseup", () => follow.classList.remove("active"));

  window.addEventListener("pagehide", () => {
    if (raf) cancelAnimationFrame(raf);
  }, { once: true });
})();
